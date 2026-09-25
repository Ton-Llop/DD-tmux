from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TD_")

    database_url: str = "postgresql://dungeon:dungeon@localhost:5432/dungeon"
    # Token obligatorio: este servicio da acceso a una shell. Sin token no arranca.
    auth_token: str = ""
    # Cada cuánto se escanea tmux (segundos)
    poll_interval: float = 0.5
    # Líneas de scrollback que se capturan por pane
    capture_lines: int = 200
    # Un pane se considera "working" si su pantalla cambió en los últimos N segundos
    busy_window: float = 3.0
    # Mínimo de segundos entre snapshots persistidos del mismo pane
    persist_interval: float = 5.0
    # Días que se guardan los eventos
    retention_days: int = 14
    # Socket de tmux alternativo (-L), vacío = el por defecto
    tmux_socket: str = ""


settings = Settings()
