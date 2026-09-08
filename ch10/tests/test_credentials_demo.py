"""凭证演示不能向模型提供宿主机 Shell；无需真实 API。"""
import importlib.util
from pathlib import Path

from langchain_core.messages import AIMessage
from deepagents.backends.protocol import SandboxBackendProtocol


def test_credentials_demo_has_no_host_shell(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "03_security_closure.py"
    spec = importlib.util.spec_from_file_location("security_demo", path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    monkeypatch.setattr(demo, "make_model", lambda **kwargs: object())

    def create_agent(**kwargs):
        # 旧实现的 LocalShellBackend 会在这里失败：它向模型开放 execute。
        assert not isinstance(kwargs["backend"], SandboxBackendProtocol)
        weather = kwargs["tools"][0].invoke({"city": "北京"})
        assert "北京" in weather
        assert demo.HOST_SIDE_API_KEY not in weather

        class Agent:
            def invoke(self, inputs, **config):
                return {"messages": [AIMessage(content="北京晴，工作区未发现凭证。") ]}

        return Agent()

    monkeypatch.setattr(demo, "create_deep_agent", create_agent)
    demo.part_a_credentials_outside_sandbox()
