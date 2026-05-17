from __future__ import annotations

import random

from .header_profiles import HEADER_PROFILES, HeaderProfile


def _base_headers(profile: HeaderProfile) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Encoding": profile.accept_encoding,
        "Accept-Language": profile.accept_language,
        "Cache-Control": profile.cache_control,
        "Connection": profile.connection,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": profile.sec_fetch_site,
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": profile.user_agent,
    }

    if profile.dnt is not None:
        headers["DNT"] = profile.dnt
    if profile.sec_gpc is not None:
        headers["Sec-GPC"] = profile.sec_gpc
    if profile.sec_ch_ua is not None:
        headers["Sec-CH-UA"] = profile.sec_ch_ua
    if profile.sec_ch_ua_mobile is not None:
        headers["Sec-CH-UA-Mobile"] = profile.sec_ch_ua_mobile
    if profile.sec_ch_ua_platform is not None:
        headers["Sec-CH-UA-Platform"] = profile.sec_ch_ua_platform
    if profile.sec_ch_ua_arch is not None:
        headers["Sec-CH-UA-Arch"] = profile.sec_ch_ua_arch
    if profile.sec_ch_ua_bitness is not None:
        headers["Sec-CH-UA-Bitness"] = profile.sec_ch_ua_bitness
    if profile.sec_ch_ua_full_version_list is not None:
        headers["Sec-CH-UA-Full-Version-List"] = profile.sec_ch_ua_full_version_list
    if profile.sec_ch_ua_platform_version is not None:
        headers["Sec-CH-UA-Platform-Version"] = profile.sec_ch_ua_platform_version

    return headers


def get_random_header() -> dict[str, str]:
    """Generate a coherent browser-like request header set."""
    profile = random.choice(HEADER_PROFILES)
    return _base_headers(profile)
