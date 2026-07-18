from alpha_os.adapters.base import MacroDataAdapter
from alpha_os.core.models import MacroSnapshot


class MockMacroAdapter(MacroDataAdapter):
    def get_snapshot(self) -> MacroSnapshot:
        return MacroSnapshot()
