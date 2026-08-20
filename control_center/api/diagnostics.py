from aiohttp import web


async def diagnostics_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_diagnostics_service"
    ]

    return web.json_response(
        service.get_diagnostics()
    )