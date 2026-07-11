import asyncio

import mcp_server.server as server_module
from mcp_server.server import mcp


def test_mcp_server_module_imports_successfully_and_exposes_a_fastmcp_instance():
    assert server_module.mcp is mcp


def test_all_four_pipeline_tools_are_registered_on_the_fastmcp_instance():
    registered = asyncio.run(mcp.list_tools())
    registered_names = {tool.name for tool in registered}

    assert registered_names == {
        "check_sponsor",
        "check_salary_threshold",
        "track_application",
        "list_applications",
    }
