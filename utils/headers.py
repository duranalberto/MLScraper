from __future__ import annotations

import random
from importlib.util import find_spec
from dataclasses import dataclass


@dataclass(frozen=True)
class HeaderProfile:
    user_agent: str
    accept_language: str
    accept_encoding: str
    cache_control: str
    connection: str
    dnt: str | None
    sec_gpc: str | None
    sec_fetch_site: str
    sec_ch_ua: str | None
    sec_ch_ua_mobile: str | None
    sec_ch_ua_platform: str | None
    sec_ch_ua_arch: str | None = None
    sec_ch_ua_bitness: str | None = None
    sec_ch_ua_full_version_list: str | None = None
    sec_ch_ua_platform_version: str | None = None

def _supported_accept_encoding() -> str:
    encodings = ["gzip", "deflate"]
    if find_spec("brotli") is not None or find_spec("brotlicffi") is not None:
        encodings.append("br")
    return ", ".join(encodings)


_ACCEPT_ENCODING = _supported_accept_encoding()


def _chromium_profile(
    *,
    browser: str,
    version: str,
    platform: str,
    platform_version: str,
    arch: str,
    bitness: str,
    accept_language: str,
    accept_encoding: str = _ACCEPT_ENCODING,
    cache_control: str = "max-age=0",
    connection: str = "keep-alive",
    dnt: str | None = None,
    sec_gpc: str | None = None,
    sec_fetch_site: str = "none",
) -> HeaderProfile:
    brand = {
        "Chrome": "Google Chrome",
        "Edge": "Microsoft Edge",
        "Opera": "Opera",
    }.get(browser, browser)

    sec_ua = f'"Not_A Brand";v="8", "Chromium";v="{version}", "{brand}";v="{version}"'
    full_version_list = (
        f'"Not_A Brand";v="8.0.0.0", '
        f'"Chromium";v="{version}.0.0.0", '
        f'"{brand}";v="{version}.0.0.0"'
    )

    return HeaderProfile(
        user_agent=_make_chromium_ua(browser, version, platform),
        accept_language=accept_language,
        accept_encoding=accept_encoding,
        cache_control=cache_control,
        connection=connection,
        dnt=dnt,
        sec_gpc=sec_gpc,
        sec_fetch_site=sec_fetch_site,
        sec_ch_ua=sec_ua,
        sec_ch_ua_mobile='?0',
        sec_ch_ua_platform=f'"{platform}"',
        sec_ch_ua_arch=f'"{arch}"',
        sec_ch_ua_bitness=f'"{bitness}"',
        sec_ch_ua_full_version_list=full_version_list,
        sec_ch_ua_platform_version=f'"{platform_version}"',
    )


def _make_chromium_ua(browser: str, version: str, platform: str) -> str:
    if browser == "Chrome":
        if platform == "Windows":
            return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        if platform == "macOS":
            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"

    if browser == "Edge":
        if platform == "Windows":
            return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0"
        if platform == "macOS":
            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0"
        return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0"

    if browser == "Opera":
        if platform == "Windows":
            return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 OPR/{version}.0.0.0"
        if platform == "macOS":
            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 OPR/{version}.0.0.0"
        return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 OPR/{version}.0.0.0"

    raise ValueError(f"Unsupported Chromium browser profile: {browser}")


def _firefox_profile(
    *,
    version: str,
    platform: str,
    accept_language: str,
    accept_encoding: str = _ACCEPT_ENCODING,
    cache_control: str = "no-cache",
    connection: str = "keep-alive",
    dnt: str | None = "1",
    sec_gpc: str | None = "1",
    sec_fetch_site: str = "none",
) -> HeaderProfile:
    if platform == "Windows":
        ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"
    elif platform == "macOS":
        ua = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"
    else:
        ua = f"Mozilla/5.0 (X11; Linux x86_64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"

    return HeaderProfile(
        user_agent=ua,
        accept_language=accept_language,
        accept_encoding=accept_encoding,
        cache_control=cache_control,
        connection=connection,
        dnt=dnt,
        sec_gpc=sec_gpc,
        sec_fetch_site=sec_fetch_site,
        sec_ch_ua=None,
        sec_ch_ua_mobile=None,
        sec_ch_ua_platform=None,
    )


def _safari_profile(
    *,
    version: str,
    accept_language: str,
    accept_encoding: str = _ACCEPT_ENCODING,
    cache_control: str = "no-cache",
    connection: str = "keep-alive",
    dnt: str | None = "1",
    sec_gpc: str | None = "1",
    sec_fetch_site: str = "none",
) -> HeaderProfile:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        f"AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{version} Safari/605.1.15"
    )

    return HeaderProfile(
        user_agent=ua,
        accept_language=accept_language,
        accept_encoding=accept_encoding,
        cache_control=cache_control,
        connection=connection,
        dnt=dnt,
        sec_gpc=sec_gpc,
        sec_fetch_site=sec_fetch_site,
        sec_ch_ua=None,
        sec_ch_ua_mobile=None,
        sec_ch_ua_platform=None,
    )


HEADER_PROFILES: tuple[HeaderProfile, ...] = (
    _chromium_profile(
        browser="Chrome",
        version="126",
        platform="Windows",
        platform_version="15.0.0",
        arch="x86",
        bitness="64",
        accept_language="es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
    ),
    _chromium_profile(
        browser="Chrome",
        version="126",
        platform="macOS",
        platform_version="14.5.0",
        arch="arm",
        bitness="64",
        accept_language="es-419,es;q=0.9,en-US;q=0.8,en;q=0.7",
        sec_gpc="1",
    ),
    _chromium_profile(
        browser="Chrome",
        version="126",
        platform="Linux",
        platform_version="0.0.0",
        arch="x86",
        bitness="64",
        accept_language="en-US,en;q=0.9,es;q=0.8",
    ),
    _chromium_profile(
        browser="Edge",
        version="126",
        platform="Windows",
        platform_version="15.0.0",
        arch="x86",
        bitness="64",
        accept_language="es-MX,es;q=0.9,en;q=0.8",
        cache_control="no-cache",
    ),
    _chromium_profile(
        browser="Edge",
        version="126",
        platform="macOS",
        platform_version="14.5.0",
        arch="arm",
        bitness="64",
        accept_language="es-ES,es;q=0.9,en-US;q=0.8",
    ),
    _chromium_profile(
        browser="Opera",
        version="111",
        platform="Windows",
        platform_version="15.0.0",
        arch="x86",
        bitness="64",
        accept_language="es-MX,es;q=0.9,en-US;q=0.7",
        sec_fetch_site="same-origin",
    ),
    _firefox_profile(
        version="126",
        platform="Windows",
        accept_language="es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
        dnt="1",
        sec_gpc="1",
    ),
    _firefox_profile(
        version="126",
        platform="macOS",
        accept_language="es-419,es;q=0.9,en-US;q=0.8,en;q=0.7",
        dnt="1",
        sec_gpc="1",
        cache_control="max-age=0",
    ),
    _firefox_profile(
        version="126",
        platform="Linux",
        accept_language="en-US,en;q=0.9,es;q=0.8",
        dnt=None,
        sec_gpc=None,
    ),
    _safari_profile(
        version="17.5",
        accept_language="es-MX,es;q=0.9,en;q=0.8",
        dnt="1",
        sec_gpc="1",
    ),
    _safari_profile(
        version="17.5",
        accept_language="es-ES,es;q=0.9,en-US;q=0.8",
        dnt=None,
        sec_gpc=None,
        sec_fetch_site="same-site",
    ),
)


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
