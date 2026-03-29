# see https://keypirinha.com/api/overview.html
# see https://keypirinha.com/api/plugin.html
import subprocess

import keypirinha as kp


def _execute_powershell(command):
    """
    PowerShellを実行して結果を返す
    """
    args = ["powershell", "-ExecutionPolicy", "Bypass", "-Command", command]
    stdout = subprocess.run(
        args,
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    return stdout.decode("utf-8").strip()


def _list_wsl_distros():
    """
    WSLディストリビューション一覧を取得する（UTF-16-LE対応）
    """
    stdout = subprocess.run(
        ["wsl", "-l", "-q"],
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    return [d for d in stdout.decode("utf-16-le").strip().splitlines() if d]


def _execute_wsl(command: str, distro = None):
    """
    WSLを実行して結果を返す
    """
    args = ["wsl"]
    if distro:
        args += ["-d", distro]
    args += ["bash", "-lc", command]
    stdout = subprocess.run(
        args,
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    return stdout.decode("utf-8").strip()


class ReposPlugin(kp.Plugin):
    """
    リポジトリを開くクラス
    """

    # アイテムのカテゴリを定義（ユーザ定義のカテゴリは USER_BASE 以降を使用）
    ITEMCAT_RESULT = kp.ItemCategory.USER_BASE + 1

    def __init__(self):
        super().__init__()
        self._debug = True

    def on_start(self):
        """初期化"""
        # ItemCategory に CatalogAction のリストを割り当て
        self.set_actions(
            self.ITEMCAT_RESULT,
            [
                # CatalogAction オブジェクトの生成
                self.create_action(
                    name="copy", label="Copy", short_desc="Copy the name of the answer"
                )
            ],
        )

    def on_catalog(self):
        """
        カタログ生成.
        Keypirinha で起動するためのトリガー・説明など.
        """
        self.set_catalog(
            [
                self._create_item(
                    label="repos", short_desc="Open repositories", target="repos:"
                )
            ]
        )

    def on_suggest(self, user_input, items_chain):
        """検索処理

        :user_input: 入力内容
        :items_chain: 選択したアイテム
        """
        # カテゴリが異なる場合
        if not items_chain or items_chain[0].category() != kp.ItemCategory.KEYWORD:
            return

        self.dbg(
            f"User input: {user_input}, Items chain: {[item.target() for item in items_chain]}"
        )
        self.dbg(f"Items chain categories: {[item.category() for item in items_chain]}")

        suggestions = []
        if items_chain[0].target() == "repos:":
            # プラットフォーム選択
            suggestions = [
                self._create_item(
                    label="Windows",
                    short_desc="Open on Windows",
                    target="repos:windows",
                ),
                self._create_item(
                    label="WSL", short_desc="Open on WSL", target="repos:wsl"
                ),
            ]

            if len(items_chain) > 1:
                if items_chain[1].target() == "repos:windows":
                    self.dbg("Selected platform: Windows")

                    root_path = _execute_powershell("ghq root")
                    repos = _execute_powershell("ghq list").split()
                    suggestions = [
                        self._create_item(
                            label=repo,
                            short_desc=repo,
                            target=f"repos:windows:{root_path}/{repo}",
                            is_final=True,
                        )
                        for repo in repos
                    ]
                elif items_chain[1].target() == "repos:wsl":
                    self.dbg("Selected platform: WSL")

                    # WSLのディストリビューション選択
                    distros = _list_wsl_distros()
                    suggestions = [
                        self._create_item(
                            label=distro,
                            short_desc=distro,
                            target=f"repos:wsl:{distro}",
                        )
                        for distro in distros
                    ]

                    if len(items_chain) > 2 and items_chain[2].target().startswith(
                        "repos:wsl:"
                    ):
                        distro = items_chain[2].target().replace("repos:wsl:", "", 1)
                        root_path = _execute_wsl("ghq root", distro=distro)
                        repos = _execute_wsl("ghq list", distro=distro).split()
                        suggestions = [
                            self._create_item(
                                label=repo,
                                short_desc=f"{distro}: {repo}",
                                target=f"repos:wsl:{distro}:{root_path}/{repo}",
                                is_final=True,
                            )
                            for repo in repos
                        ]
                else:
                    suggestions = [
                        self.create_error_item(
                            label="Unknown platform",
                            short_desc="The selected platform is not recognized",
                        )
                    ]

        # サジェスト表示
        self.set_suggestions(
            suggestions,
            kp.Match.FUZZY,  # マッチング方式
            kp.Sort.NONE,  # ソートのルール
        )

    def on_execute(self, catalog_item, catalog_action):
        """実行処理

        :item (CatalogItem): on_suggest で選択した項目
        :action (CatalogAction): on_suggest で選択した項目に対して実行するアクション
        """
        if catalog_item.category() != self.ITEMCAT_RESULT:
            return

        if not catalog_item.target().startswith("repos:"):
            return

        # repos:platform:残り の形式で分割（pathに:が含まれる場合を考慮）
        parts = catalog_item.target().split(":", 2)
        if len(parts) < 3:
            self.err(f"Invalid target format (too few parts): {catalog_item.target()}")
            return

        platform = parts[1]
        rest = parts[2]
        try:
            if platform == "windows":
                # 形式: repos:windows:C:/path
                repo_path = rest
                command = f'code "{repo_path}"'
            elif platform == "wsl":
                # 形式: repos:wsl:distro:path (distroに:は含まれない)
                wsl_parts = rest.split(":", 1)
                if len(wsl_parts) < 2:
                    self.err(f"Invalid WSL target format: {catalog_item.target()}")
                    return
                distro = wsl_parts[0]
                repo_path = wsl_parts[1]
                command = f'code --remote wsl+{distro} "{repo_path}"'
            else:
                self.err(f"Unknown platform: {platform}")
                return
        except Exception as e:
            self.err(f"Error preparing command: {e}")
            return

        self.dbg(f"Running command: {command}")
        try:
            subprocess.run(command, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            self.err(f"Command failed with exit code {e.returncode}: {e}")

    def _create_item(
        self, label: str, short_desc: str, target: str, is_final: bool = False
    ):
        """
        CatalogItem を生成する関数
        """
        return self.create_item(
            # 入力のカテゴリ
            category=kp.ItemCategory.KEYWORD if not is_final else self.ITEMCAT_RESULT,
            label=label,  # 表示名
            short_desc=short_desc,  # 説明
            target=target,  # 起動キーワード
            # 引数を要求する
            args_hint=kp.ItemArgsHint.REQUIRED if not is_final else kp.ItemArgsHint.FORBIDDEN,  
            hit_hint=kp.ItemHitHint.NOARGS if not is_final else kp.ItemHitHint.IGNORE,
        )
