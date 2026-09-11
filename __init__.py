"""Directory-plugin entry point used by ``hermes plugins install``."""

if __package__:
    from .webhookrelay_hermes import register
else:  # Pytest imports a repository-root ``__init__.py`` as a bare module.
    from webhookrelay_hermes import register

__all__ = ["register"]
