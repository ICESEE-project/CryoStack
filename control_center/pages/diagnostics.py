from aiohttp import web

from .ops import diagnostics_page_handler as _diagnostics_page


async def diagnostics_page_handler(
    request: web.Request,
) -> web.Response:

    return await _diagnostics_page(
        request
    )
