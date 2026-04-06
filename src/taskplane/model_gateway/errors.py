from __future__ import annotations


class ModelGatewayError(RuntimeError):
    pass


class LLMRequestError(ModelGatewayError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason_code: str = "upstream_api_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code
        self.retryable = retryable


class ProviderConfigurationError(ModelGatewayError):
    pass


class ModelProtocolError(ModelGatewayError):
    pass


class ModelTimeoutError(ModelGatewayError):
    pass
