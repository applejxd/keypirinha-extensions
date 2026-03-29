# see https://keypirinha.com/api/plugin.html
import subprocess
import threading

import keypirinha as kp


class _BasePlugin(kp.Plugin):
    """
    リポジトリを開くクラスの抽象基底クラス
    """

    ITEMCAT_RESULT = kp.ItemCategory.USER_BASE + 1

    def __init__(self):
        super().__init__()
        # インスタンス変数として初期化（クラス変数の共有を避ける）
        self.root_path = ""
        self.repos = []

    def on_start(self):
        """初期化"""
        self.repos = []
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
        pass

    def on_suggest(self, user_input, items_chain):
        """検索処理

        Args:
            user_input : 入力内容
            items_chain : 選択したアイテム
        """
        # カテゴリが異なる場合
        if not items_chain or items_chain[-1].category() != kp.ItemCategory.KEYWORD:
            return

        # サジェスト作成
        suggestions = [
            # CatalogItem オブジェクト生成
            self.create_item(
                category=self.ITEMCAT_RESULT,
                label=self.repos[idx],
                short_desc=self.repos[idx],
                target=self.repos[idx],
                args_hint=kp.ItemArgsHint.FORBIDDEN,
                hit_hint=kp.ItemHitHint.IGNORE,
            )
            # 降順ループ
            for idx in range(0, len(self.repos))
        ]

        # サジェスト表示
        self.set_suggestions(
            suggestions,
            # マッチング方式
            kp.Match.FUZZY,
            # ソートのルール
            kp.Sort.NONE,
        )

    def on_execute(self, item, action):
        """実行処理

        Args:
            item (CatalogItem): on_suggest で選択した項目
            action (CatalogAction): [description]
        """
        # パスにスペースが含まれる場合も正しく動作するようクォートする
        command = f'{self.open_command} "{self.root_path}/{item.target()}"'
        subprocess.run(command, shell=True, check=True)


class GhqWindows(_BasePlugin):
    def __init__(self):
        super().__init__()
        self.open_command = "code"

    def on_start(self):
        """初期化"""
        super().on_start()
        self.root_path = (
            subprocess.run(
                "powershell -ExecutionPolicy Bypass ghq root",
                shell=True,
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )
        # バイナリ文字列を変換・改行コードでリスト化
        self.repos = (
            subprocess.run(
                "powershell -ExecutionPolicy Bypass ghq list",
                shell=True,
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode("utf-8")
            .split()
        )

    def on_catalog(self):
        """
        カタログ生成.
        Keypirinha で起動するためのトリガー・説明など.
        """
        # CatalogItem のリストで catalog の変更
        self.set_catalog(
            [
                # CatalogItem 生成
                self.create_item(
                    # 入力のカテゴリ
                    category=kp.ItemCategory.KEYWORD,
                    # 表示名
                    label="repos (ghq for Windows)",
                    # 説明
                    short_desc="Open repositories",
                    # 起動キーワード
                    target="repos_win",
                    # 引数を要求する
                    args_hint=kp.ItemArgsHint.REQUIRED,
                    # 重複なしで履歴を保存
                    hit_hint=kp.ItemHitHint.NOARGS,
                )
            ]
        )


class SrcWindows(_BasePlugin):
    def __init__(self):
        super().__init__()
        self.open_command = "code"

    def on_start(self):
        """初期化"""
        super().on_start()
        self.root_path = (
            subprocess.run(
                "powershell -ExecutionPolicy Bypass $env:UserProfile",
                shell=True,
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode("utf-8")
            .strip()
            + "\\src"
        )
        # バイナリ文字列を変換・改行コードでリスト化
        self.repos = (
            subprocess.run(
                "powershell -ExecutionPolicy Bypass Get-ChildItem $env:UserProfile\\src -Name",
                shell=True,
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode("utf-8")
            .split()
        )

    def on_catalog(self):
        """
        カタログ生成.
        Keypirinha で起動するためのトリガー・説明など.
        """
        # CatalogItem のリストで catalog の変更
        self.set_catalog(
            [
                # CatalogItem 生成
                self.create_item(
                    # 入力のカテゴリ
                    category=kp.ItemCategory.KEYWORD,
                    # 表示名
                    label="repos (src folder in Windows)",
                    # 説明
                    short_desc="Open repositories",
                    # 起動キーワード
                    target="repos_src_win",
                    # 引数を要求する
                    args_hint=kp.ItemArgsHint.REQUIRED,
                    # 重複なしで履歴を保存
                    hit_hint=kp.ItemHitHint.NOARGS,
                )
            ]
        )


class GhqWsl(_BasePlugin):
    CMD_ROOT = "repos_ghq"
    CMD_DISTRO = "repos_ghq:distro:"
    CMD_REPO = "repos_ghq:repo:"

    def __init__(self):
        super().__init__()

        self.open_command = "wsl code"
        self.distros = []
        self.roots_by_distro = {}
        self.repos_by_distro = {}
        self._cache_lock = threading.Lock()
        self._cache_warm_started = False

    def on_start(self):
        """初期化"""
        super().on_start()
        self.distros = []
        self.roots_by_distro = {}
        self.repos_by_distro = {}
        self._cache_warm_started = False
        self._warm_cache_async()

    def _run_wsl(self, args):
        completed = subprocess.run(
            ["wsl", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def _list_distros(self):
        return self._run_wsl(["-l", "-q"]).split()

    def _ensure_distros_loaded(self):
        if self.distros:
            return self.distros

        with self._cache_lock:
            if not self.distros:
                self.distros = self._list_distros()
        return self.distros

    def _load_distro_repos(self, distro):
        with self._cache_lock:
            if distro not in self.roots_by_distro:
                self.roots_by_distro[distro] = self._run_wsl(
                    ["-d", distro, "bash", "-lc", "ghq root"]
                )

            if distro not in self.repos_by_distro:
                # ghq は login shell の PATH に載るため -l が必要
                self.repos_by_distro[distro] = self._run_wsl(
                    ["-d", distro, "bash", "-lc", "ghq list"]
                ).split()
        return self.roots_by_distro[distro], self.repos_by_distro[distro]

    def _warm_cache(self):
        try:
            for distro in self._ensure_distros_loaded():
                self._load_distro_repos(distro)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return

    def _warm_cache_async(self):
        if self._cache_warm_started:
            return

        self._cache_warm_started = True
        threading.Thread(target=self._warm_cache, daemon=True).start()

    def _suggest_distros(self):
        try:
            distros = self._ensure_distros_loaded()
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            self.set_suggestions(
                [
                    self.create_error_item(
                        label="Failed to load WSL distributions",
                        short_desc=str(exc),
                    )
                ],
                kp.Match.ANY,
                kp.Sort.NONE,
            )
            return

        suggestions = [
            self.create_item(
                category=kp.ItemCategory.KEYWORD,
                label=distro,
                short_desc=f"Browse ghq repositories in {distro}",
                target=f"{self.CMD_DISTRO}{distro}",
                args_hint=kp.ItemArgsHint.REQUIRED,
                hit_hint=kp.ItemHitHint.KEEPALL,
            )
            for distro in distros
        ]
        self.set_suggestions(suggestions, kp.Match.FUZZY, kp.Sort.NONE)

    def _suggest_repos(self, distro, user_input):
        try:
            root_path, repos = self._load_distro_repos(distro)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            self.set_suggestions(
                [
                    self.create_error_item(
                        label=f"{distro}: failed to load ghq repositories",
                        short_desc=str(exc),
                    )
                ],
                kp.Match.ANY,
                kp.Sort.NONE,
            )
            return

        if user_input:
            query = user_input.lower()
            repos = [repo for repo in repos if query in repo.lower()]

        if not repos:
            self.set_suggestions(
                [
                    self.create_error_item(
                        label=f"{distro}: no repositories found",
                        short_desc="ghq list returned no repositories",
                    )
                ],
                kp.Match.ANY,
                kp.Sort.NONE,
            )
            return

        suggestions = [
            self.create_item(
                category=self.ITEMCAT_RESULT,
                label=repo,
                short_desc=f"{distro}: {repo}",
                target=f"{self.CMD_REPO}{distro}\t{root_path}\t{repo}",
                args_hint=kp.ItemArgsHint.FORBIDDEN,
                hit_hint=kp.ItemHitHint.IGNORE,
            )
            for repo in repos
        ]
        self.set_suggestions(suggestions, kp.Match.FUZZY, kp.Sort.NONE)

    def on_suggest(self, user_input, items_chain):
        if not items_chain or items_chain[0].category() != kp.ItemCategory.KEYWORD:
            return

        if items_chain[0].target() != self.CMD_ROOT:
            return

        if len(items_chain) == 1:
            self._suggest_distros()
            return

        if len(items_chain) >= 2 and items_chain[1].target().startswith(self.CMD_DISTRO):
            distro = items_chain[1].target().replace(self.CMD_DISTRO, "", 1)
            self._suggest_repos(distro, user_input.strip())
            return

        if (
            items_chain[-1].category() == kp.ItemCategory.KEYWORD
            and items_chain[-1].target() in self.distros
        ):
            self._suggest_repos(items_chain[-1].target(), user_input.strip())
            return

    def on_execute(self, item, action):
        if item.category() != self.ITEMCAT_RESULT:
            return

        if not item.target().startswith(self.CMD_REPO):
            return

        distro, root_path, repo = item.target().replace(self.CMD_REPO, "", 1).split(
            "\t", 2
        )
        command = f'wsl -d "{distro}" code "{root_path}/{repo}"'
        subprocess.run(command, shell=True, check=True)

    def on_catalog(self):
        """
        カタログ生成.
        Keypirinha で起動するためのトリガー・説明など.
        """
        # CatalogItem のリストで catalog の変更
        self.set_catalog(
            [
                # CatalogItem 生成
                self.create_item(
                    # 入力のカテゴリ
                    category=kp.ItemCategory.KEYWORD,
                    # 表示名
                    label="repos (ghq for WSL)",
                    # 説明
                    short_desc="Open repositories",
                    # 起動キーワード
                    target=self.CMD_ROOT,
                    # 引数を要求する
                    args_hint=kp.ItemArgsHint.REQUIRED,
                    # 重複なしで履歴を保存
                    hit_hint=kp.ItemHitHint.KEEPALL,
                )
            ]
        )
