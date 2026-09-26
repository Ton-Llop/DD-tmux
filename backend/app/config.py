from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TD_")

    database_url: str = "postgresql://dungeon:dungeon@localhost:5432/dungeon"
    # Mandatory token: this service grants shell access. It won't start without one.
    auth_token: str = ""
    # How often tmux is scanned (seconds)
    poll_interval: float = 0.5
    # Scrollback lines captured per pane
    capture_lines: int = 200
    # A pane counts as "working" if its screen changed in the last N seconds
    busy_window: float = 3.0
    # Minimum seconds between persisted snapshots of the same pane
    persist_interval: float = 5.0
    # Days events are kept
    retention_days: int = 14
    # Alternative tmux socket (-L), empty = the default
    tmux_socket: str = ""


settings = Settings()
