"""Synchronize reviewed Aurinara access contracts with the shared Platform."""

from app.config import get_settings
from app.platform.access_catalog import permission_catalog
from app.platform.authorization import PlatformAuthorizationClient


def main() -> None:
    settings = get_settings()
    if settings.platform_authorization_mode == "disabled":
        print("platform_access=skipped")
        return
    client = PlatformAuthorizationClient(settings)
    expected_permissions = {str(item["code"]) for item in permission_catalog()}
    registered_permissions = set(client.sync_permissions(permission_catalog()))
    if registered_permissions != expected_permissions:
        raise RuntimeError("Platform did not preserve the Aurinara permission catalog")
    print("platform_access=ready")


if __name__ == "__main__":
    main()
