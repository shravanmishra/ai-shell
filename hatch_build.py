"""Optional wheel build hook: bundles the GGUF weights when present locally.

`uv build` / `pip wheel` stay unaffected for everyone who doesn't have the
model file checked out -- this only fires when the file exists, so it never
turns a routine build into a hard failure over a missing multi-hundred-MB
asset. To cut a wheel with the model baked in, put the GGUF at the path
below (or point SHELLAI_BUNDLE_GGUF at it) before running `uv build`.
"""

import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

DEFAULT_SRC = os.path.join("llm", "gguf", "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf")


class BundleGGUFHook(BuildHookInterface):
    def initialize(self, version, build_data):
        src = os.environ.get("SHELLAI_BUNDLE_GGUF", DEFAULT_SRC)
        if not os.path.isfile(src):
            return
        dest = f"ai_shell/gguf/{os.path.basename(src)}"
        build_data["force_include"][src] = dest
