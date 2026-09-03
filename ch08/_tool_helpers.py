"""05 脚本的工具函数抽取（供脚本与测试共用）：情景日志归档 + 检索工具构造。"""

from deepagents.backends.utils import create_file_data


def seed_episode(store, namespace, ep_id: str, date: str, content: str):
    """归档一篇情景日志（对话结束后调用）。"""
    store.put(namespace, f"/episodes/{ep_id}.md",
              create_file_data(f"# 情景 {date}\n\n{content}\n"))


def make_search_episodes_tool(store, namespace):
    """给 Agent 的情景检索工具：按关键词扫描全部情景日志。"""

    def search_episodes(query: str) -> str:
        """搜索过去的对话情景（episode 日志），返回与关键词相关的经历摘要。

        Args:
            query: 检索关键词，例如 'GIL'、'排序函数'。
        """
        hits = []
        for item in store.search(namespace):
            if not item.key.startswith("/episodes/"):
                continue
            content = item.value.get("content", "")
            if query.lower() in content.lower():
                hits.append(f"--- {item.key} ---\n{content[:400]}")
        return "\n\n".join(hits) if hits else f"没有找到与 '{query}' 相关的过去情景。"

    return search_episodes
