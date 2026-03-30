"""WslSsh プラグイン — WSL の ~/.ssh/config を読み取り SSH 接続する.

WSL デフォルトディストリビューションの SSH config から Host エントリを取得し、
Windows Terminal + WSL 経由で SSH 接続を行う。

See:
    https://keypirinha.com/api/overview.html
    https://keypirinha.com/api/plugin.html
"""

import re
import subprocess

import keypirinha as kp
import keypirinha_util as kpu

# ターゲット文字列のプレフィックス
_PREFIX = "wslssh:"


# ------------------------------------------------------------------
# 外部コマンド実行ヘルパー
# ------------------------------------------------------------------

def _run_wsl(command):
    """WSL デフォルトディストリビューションでコマンドを実行し、標準出力を返す."""
    args = ["wsl", "bash", "-lc", command]
    result = subprocess.run(
        args,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


def _parse_ssh_config(raw_config):
    """SSH config テキストから Host エントリ名のリストを返す.

    ワイルドカード (``*``, ``?``) を含むエントリは除外する。
    ``Host foo bar`` のように複数ホストが並ぶ場合は個別に分割する。
    """
    pattern = re.compile(r"^Host\s+(.+)$", re.IGNORECASE)
    hosts = []
    for line in raw_config.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        for host in m.group(1).split():
            host = host.strip()
            if host and "*" not in host and "?" not in host:
                hosts.append(host)
    return hosts


# ------------------------------------------------------------------
# プラグイン本体
# ------------------------------------------------------------------

class WslSshPlugin(kp.Plugin):
    """WSL SSH config のホスト一覧から SSH 接続する Keypirinha プラグイン.

    カタログ項目 "ssh" → ホスト選択 → Windows Terminal で SSH 実行
    の 2 段階でサジェストを構成する。
    """

    CONFIG_SECTION_MAIN = "main"

    # ユーザ定義カテゴリ (USER_BASE 以降を使用)
    ITEMCAT_RESULT = kp.ItemCategory.USER_BASE + 1

    # デフォルト設定
    DEFAULT_WT_PROFILE = "Ubuntu"
    DEFAULT_SSH_CONFIG_PATH = "~/.ssh/config"

    def __init__(self):
        super().__init__()
        self._debug = True
        self._wt_profile = self.DEFAULT_WT_PROFILE
        self._ssh_config_path = self.DEFAULT_SSH_CONFIG_PATH
        self._ssh_hosts = []

    # ------------------------------------------------------------------
    # Keypirinha イベントハンドラ
    # ------------------------------------------------------------------

    def on_start(self):
        """プラグイン起動時の初期化。設定読み込みと SSH config 取得を行う。"""
        self._load_config()
        self._refresh_ssh_hosts()

        self.set_actions(
            self.ITEMCAT_RESULT,
            [
                self.create_action(
                    name="copy",
                    label="Copy",
                    short_desc="Copy the host name",
                ),
            ],
        )

    def on_catalog(self):
        """カタログ登録。Keypirinha のトリガーキーワードを定義する。"""
        self.set_catalog(
            [
                self.create_item(
                    category=kp.ItemCategory.KEYWORD,
                    label="SSH",
                    short_desc="SSH to hosts defined in WSL ~/.ssh/config",
                    target=_PREFIX,
                    args_hint=kp.ItemArgsHint.REQUIRED,
                    hit_hint=kp.ItemHitHint.NOARGS,
                ),
            ]
        )

    def on_suggest(self, user_input, items_chain):
        """サジェスト表示。SSH ホスト一覧をファジーフィルタで候補表示する。"""
        if not items_chain or items_chain[0].category() != kp.ItemCategory.KEYWORD:
            return

        self.dbg(f"User input: {user_input}")

        suggestions = [
            self.create_item(
                category=self.ITEMCAT_RESULT,
                label=host,
                short_desc=f"ssh {host}",
                target=f"{_PREFIX}{host}",
                args_hint=kp.ItemArgsHint.FORBIDDEN,
                hit_hint=kp.ItemHitHint.IGNORE,
            )
            for host in self._ssh_hosts
        ]
        self.set_suggestions(suggestions, kp.Match.FUZZY, kp.Sort.LABEL_ASC)

    def on_execute(self, catalog_item, catalog_action):
        """選択されたホストに Windows Terminal + WSL 経由で SSH 接続する。"""
        if catalog_item.category() != self.ITEMCAT_RESULT:
            return
        if not catalog_item.target().startswith(_PREFIX):
            return

        host = catalog_item.target().replace(_PREFIX, "", 1)

        if catalog_action and catalog_action.name() == "copy":
            kpu.set_clipboard(host)
            return

        # Windows Terminal で WSL SSH を実行
        args = f'-p "{self._wt_profile}" wsl ssh {host}'
        self.dbg(f"Launching: wt {args}")

        try:
            kpu.shell_execute("wt", args)
        except Exception as exc:
            self.err(f"Failed to launch Windows Terminal: {exc}")

    def on_events(self, flags):
        """設定変更時に SSH config を再読み込みする。"""
        if flags & kp.Events.PACKCONFIG:
            self._load_config()
            self._refresh_ssh_hosts()
            self.on_catalog()

    # ------------------------------------------------------------------
    # 内部メソッド
    # ------------------------------------------------------------------

    def _load_config(self):
        """設定ファイルから値を読み込む。"""
        settings = self.load_settings()

        self._wt_profile = settings.get(
            "wt_profile",
            section=self.CONFIG_SECTION_MAIN,
            fallback=self.DEFAULT_WT_PROFILE,
        )

        self._ssh_config_path = settings.get(
            "ssh_config_path",
            section=self.CONFIG_SECTION_MAIN,
            fallback=self.DEFAULT_SSH_CONFIG_PATH,
        )

        self.dbg(
            f"Config loaded: wt_profile={self._wt_profile}, "
            f"ssh_config_path={self._ssh_config_path}"
        )

    def _refresh_ssh_hosts(self):
        """WSL の SSH config を読み取りホスト一覧を更新する。"""
        try:
            raw_config = _run_wsl(f"cat {self._ssh_config_path}")
            self._ssh_hosts = _parse_ssh_config(raw_config)
            self.info(f"Loaded {len(self._ssh_hosts)} SSH host(s)")
        except subprocess.CalledProcessError as exc:
            self.err(f"Failed to read SSH config: {exc}")
            self._ssh_hosts = []
        except Exception as exc:
            self.err(f"Unexpected error reading SSH config: {exc}")
            self._ssh_hosts = []
