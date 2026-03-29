"""Repos プラグイン — ghq 管理リポジトリを Keypirinha から検索・VS Code で開く.

Windows / WSL 上のリポジトリを対象とする。
ghq がインストール済みであることが前提。

See:
    https://keypirinha.com/api/overview.html
    https://keypirinha.com/api/plugin.html
"""

import subprocess

import keypirinha as kp

# ターゲット文字列のプレフィックス
_PREFIX_ROOT = "repos:"
_PREFIX_WINDOWS = "repos:windows"
_PREFIX_WSL = "repos:wsl"
_PREFIX_WSL_DISTRO = "repos:wsl:"


# ------------------------------------------------------------------
# 外部コマンド実行ヘルパー
# ------------------------------------------------------------------

def _run_powershell(command):
    """PowerShell コマンドを実行し、標準出力を文字列で返す。"""
    args = ["powershell", "-ExecutionPolicy", "Bypass", "-Command", command]
    result = subprocess.run(
        args,
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


def _list_wsl_distros():
    """WSL ディストリビューション一覧を取得する。

    ``wsl -l -q`` は UTF-16-LE で出力するため専用デコードを行う。
    """
    result = subprocess.run(
        ["wsl", "-l", "-q"],
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    return [d for d in result.stdout.decode("utf-16-le").strip().splitlines() if d]


def _run_wsl(command, distro=None):
    """WSL 上でコマンドを実行し、標準出力を文字列で返す。"""
    args = ["wsl"]
    if distro:
        args += ["-d", distro]
    args += ["bash", "-lc", command]
    result = subprocess.run(
        args,
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


# ------------------------------------------------------------------
# プラグイン本体
# ------------------------------------------------------------------

class ReposPlugin(kp.Plugin):
    """ghq リポジトリを検索して VS Code で開く Keypirinha プラグイン。

    カタログ項目 "repos" → プラットフォーム選択 → リポジトリ選択 の
    3 段階でサジェストを構成する。
    """

    # ユーザ定義カテゴリ (USER_BASE 以降を使用)
    ITEMCAT_RESULT = kp.ItemCategory.USER_BASE + 1

    def __init__(self):
        super().__init__()
        self._debug = True

    # ------------------------------------------------------------------
    # Keypirinha イベントハンドラ
    # ------------------------------------------------------------------

    def on_start(self):
        """プラグイン起動時の初期化。CatalogAction を登録する。"""
        self.set_actions(
            self.ITEMCAT_RESULT,
            [
                self.create_action(
                    name="copy",
                    label="Copy",
                    short_desc="Copy the name of the answer",
                )
            ],
        )

    def on_catalog(self):
        """カタログ登録。Keypirinha のトリガーキーワードを定義する。"""
        self.set_catalog(
            [
                self._make_item(
                    label="repos",
                    short_desc="Open repositories",
                    target=_PREFIX_ROOT,
                )
            ]
        )

    def on_suggest(self, user_input, items_chain):
        """サジェスト表示。items_chain の深さに応じて候補を切り替える。"""
        if not items_chain or items_chain[0].category() != kp.ItemCategory.KEYWORD:
            return

        self.dbg(
            f"User input: {user_input}, "
            f"Items chain: {[item.target() for item in items_chain]}"
        )

        suggestions = self._build_suggestions(items_chain)
        self.set_suggestions(suggestions, kp.Match.FUZZY, kp.Sort.NONE)

    def on_execute(self, catalog_item, catalog_action):
        """選択されたリポジトリを VS Code で開く。"""
        if catalog_item.category() != self.ITEMCAT_RESULT:
            return
        if not catalog_item.target().startswith(_PREFIX_ROOT):
            return

        command = self._build_vscode_command(catalog_item.target())
        if command is None:
            return

        self.dbg(f"Running command: {command}")
        try:
            subprocess.run(command, shell=True, check=True)
        except subprocess.CalledProcessError as exc:
            self.err(f"Command failed (exit {exc.returncode}): {exc}")

    # ------------------------------------------------------------------
    # サジェスト構築
    # ------------------------------------------------------------------

    def _build_suggestions(self, items_chain):
        """items_chain の深さに応じたサジェストリストを返す。"""
        if items_chain[0].target() != _PREFIX_ROOT:
            return []

        # 第 1 階層: プラットフォーム選択
        platform_items = [
            self._make_item(
                label="Windows",
                short_desc="Open on Windows",
                target=_PREFIX_WINDOWS,
            ),
            self._make_item(
                label="WSL",
                short_desc="Open on WSL",
                target=_PREFIX_WSL,
            ),
        ]

        if len(items_chain) < 2:
            return platform_items

        # 第 2 階層以降: プラットフォーム固有の処理へ分岐
        second_target = items_chain[1].target()

        if second_target == _PREFIX_WINDOWS:
            return self._suggest_windows_repos()

        if second_target == _PREFIX_WSL:
            return self._suggest_wsl(items_chain)

        return [
            self.create_error_item(
                label="Unknown platform",
                short_desc="The selected platform is not recognized",
            )
        ]

    def _suggest_windows_repos(self):
        """Windows 上の ghq リポジトリ一覧をサジェスト用アイテムとして返す。"""
        self.dbg("Selected platform: Windows")
        root_path = _run_powershell("ghq root")
        repos = _run_powershell("ghq list").split()
        return [
            self._make_item(
                label=repo,
                short_desc=repo,
                target=f"repos:windows:{root_path}/{repo}",
                is_final=True,
            )
            for repo in repos
        ]

    def _suggest_wsl(self, items_chain):
        """WSL 関連のサジェストを返す。ディストロ→リポジトリの 2 段階。"""
        self.dbg("Selected platform: WSL")

        # 第 3 階層: ディストロが選択済みならリポジトリ一覧
        if len(items_chain) > 2 and items_chain[2].target().startswith(
            _PREFIX_WSL_DISTRO
        ):
            distro = items_chain[2].target().replace(_PREFIX_WSL_DISTRO, "", 1)
            return self._suggest_wsl_repos(distro)

        # 第 2 階層: ディストリビューション選択
        distros = _list_wsl_distros()
        return [
            self._make_item(
                label=distro,
                short_desc=distro,
                target=f"{_PREFIX_WSL_DISTRO}{distro}",
            )
            for distro in distros
        ]

    def _suggest_wsl_repos(self, distro):
        """指定ディストリビューション上の ghq リポジトリ一覧を返す。"""
        root_path = _run_wsl("ghq root", distro=distro)
        repos = _run_wsl("ghq list", distro=distro).split()
        return [
            self._make_item(
                label=repo,
                short_desc=f"{distro}: {repo}",
                target=f"repos:wsl:{distro}:{root_path}/{repo}",
                is_final=True,
            )
            for repo in repos
        ]

    # ------------------------------------------------------------------
    # 実行コマンド組み立て
    # ------------------------------------------------------------------

    def _build_vscode_command(self, target):
        """target 文字列から VS Code 起動コマンドを組み立てる。

        組み立てに失敗した場合は None を返す。
        """
        # "repos:platform:rest" — パスに : を含む場合があるため maxsplit=2
        parts = target.split(":", 2)
        if len(parts) < 3:
            self.err(f"Invalid target format (too few parts): {target}")
            return None

        platform = parts[1]
        rest = parts[2]

        if platform == "windows":
            # repos:windows:<path>
            return f'code "{rest}"'

        if platform == "wsl":
            # repos:wsl:<distro>:<path> — distro に : は含まれない
            wsl_parts = rest.split(":", 1)
            if len(wsl_parts) < 2:
                self.err(f"Invalid WSL target format: {target}")
                return None
            distro, repo_path = wsl_parts
            return f'code --remote wsl+{distro} "{repo_path}"'

        self.err(f"Unknown platform: {platform}")
        return None

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------

    def _make_item(self, label, short_desc, target, is_final=False):
        """CatalogItem を生成するヘルパー。

        is_final=True の場合、リポジトリ選択確定用のアイテム (ITEMCAT_RESULT)
        を返す。False の場合は次の階層へ進むための中間アイテムを返す。
        """
        return self.create_item(
            category=self.ITEMCAT_RESULT if is_final else kp.ItemCategory.KEYWORD,
            label=label,
            short_desc=short_desc,
            target=target,
            args_hint=(
                kp.ItemArgsHint.FORBIDDEN if is_final
                else kp.ItemArgsHint.REQUIRED
            ),
            hit_hint=(
                kp.ItemHitHint.IGNORE if is_final
                else kp.ItemHitHint.NOARGS
            ),
        )
