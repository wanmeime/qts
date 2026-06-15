# -*- coding: utf-8 -*-
"""
缠论知识库查询模块

基于 Qdrant 向量数据库和 BGE-M3 嵌入模型，
提供缠论理论知识的语义搜索和按需查询。
"""

import requests
from typing import Dict, List, Optional


class ChanlunKnowledgeBase:
    """缠论知识库查询模块"""

    def __init__(self, qdrant_url: str = "http://localhost:6333",
                 embedding_url: str = "http://localhost:6335",
                 collection: str = "chanlun_knowledge"):
        self.qdrant_url = qdrant_url
        self.embedding_url = embedding_url
        self.collection = collection
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # 连接状态
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """检查知识库服务是否可用"""
        if self._available is not None:
            return self._available
        try:
            resp = requests.get(
                f"{self.qdrant_url}/collections/{self.collection}",
                timeout=3,
            )
            self._available = resp.status_code == 200
        except requests.ConnectionError:
            self._available = False
        return self._available

    # ------------------------------------------------------------------
    # 向量嵌入
    # ------------------------------------------------------------------
    def _get_embedding(self, text: str) -> List[float]:
        """获取单条文本的向量嵌入"""
        resp = requests.post(
            f"{self.embedding_url}/v1/embeddings",
            json={"input": text, "model": "bge-m3"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """批量获取文本的向量嵌入"""
        resp = requests.post(
            f"{self.embedding_url}/v1/embeddings",
            json={"input": texts, "model": "bge-m3"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])
        return [item["embedding"] for item in data]

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        语义搜索知识库

        返回最相关的 top_k 个文档片段，每个包含：
        - score: 相似度分数
        - file_path: 来源文件
        - content: 文本内容
        """
        if not self.is_available():
            return []

        try:
            embedding = self._get_embedding(query)
            resp = requests.post(
                f"{self.qdrant_url}/collections/{self.collection}/points/search",
                json={
                    "vector": embedding,
                    "limit": top_k,
                    "with_payload": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
        except Exception:
            return []

        results = []
        for item in resp.json().get("result", []):
            payload = item.get("payload", {})
            results.append({
                "score": item.get("score", 0),
                "file_path": payload.get("file_path", ""),
                "content": payload.get("content", ""),
            })
        return results

    # ------------------------------------------------------------------
    # 便捷查询
    # ------------------------------------------------------------------
    def get_concept(self, concept_name: str) -> Dict:
        """
        获取特定缠论概念的详细信息

        例如：get_concept("中枢")、get_concept("顶分型")
        """
        query = f"缠论概念定义 {concept_name}"
        results = self.search(query, top_k=2)

        if not results:
            return {"concept": concept_name, "found": False, "content": ""}

        # 合并前两个结果的文本
        content = "\n\n".join(r["content"] for r in results)
        return {
            "concept": concept_name,
            "found": True,
            "content": content,
            "source": results[0]["file_path"],
        }

    def get_buy_sell_rules(self, point_type: str) -> Dict:
        """
        获取买卖点规则

        point_type: "buy1", "buy2", "buy3", "sell1", "sell2", "sell3"
        """
        type_names = {
            "buy1": "一类买点", "buy2": "二类买点", "buy3": "三类买点",
            "sell1": "一类卖点", "sell2": "二类卖点", "sell3": "三类卖点",
        }
        cn_name = type_names.get(point_type, point_type)
        query = f"缠论买卖点规则 {cn_name} 定义条件"
        results = self.search(query, top_k=3)

        if not results:
            return {"point_type": point_type, "found": False, "content": ""}

        content = "\n\n".join(r["content"] for r in results)
        return {
            "point_type": point_type,
            "cn_name": cn_name,
            "found": True,
            "content": content,
            "sources": [r["file_path"] for r in results],
        }

    def get_macd_rules(self) -> Dict:
        """获取 MACD 辅助判断规则"""
        results = self.search("MACD 背驰 辅助判断 金叉 死叉", top_k=3)

        if not results:
            return {"found": False, "content": ""}

        content = "\n\n".join(r["content"] for r in results)
        return {
            "found": True,
            "content": content,
            "sources": [r["file_path"] for r in results],
        }

    def get_zhong_shu_rules(self) -> Dict:
        """获取中枢相关规则"""
        results = self.search("中枢 定义 扩展 延伸 级别", top_k=3)

        if not results:
            return {"found": False, "content": ""}

        content = "\n\n".join(r["content"] for r in results)
        return {
            "found": True,
            "content": content,
            "sources": [r["file_path"] for r in results],
        }

    def enhance_analysis(self, analysis_context: str, top_k: int = 3) -> Dict:
        """
        根据当前分析上下文，检索相关知识库内容进行增强

        analysis_context: 描述当前分析中发现的形态/信号，如
            "发现二类买点，底分型，MACD底背驰"
        """
        results = self.search(analysis_context, top_k=top_k)

        if not results:
            return {"enhanced": False, "references": []}

        references = []
        for r in results:
            references.append({
                "score": r["score"],
                "source": r["file_path"],
                "content": r["content"],
            })

        return {
            "enhanced": True,
            "references": references,
        }
