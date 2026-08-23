"""Safe SuperDocs integration failures with no provider payload exposure."""


class SuperDocsError(RuntimeError):
    """Base error for the narrowly scoped SuperDocs integration."""


class SuperDocsNotConfiguredError(SuperDocsError):
    """Raised only when the optional review integration lacks its API key."""


class SuperDocsUnavailableError(SuperDocsError):
    """Raised for safe transport, timeout, and transient provider failures."""


class SuperDocsProtocolError(SuperDocsError):
    """Raised when a provider response cannot satisfy the expected contract."""
