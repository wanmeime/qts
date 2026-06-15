import os
import json
import hashlib
import requests
from pathlib import Path

# Qdrant 配置
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333

# BGE-M3 配置
EMBEDDING_HOST = "localhost"
EMBEDDING_PORT = 6335

# 知识库路径
KNOWLEDGE_BASE_PATH = "/home/jiaod/qts/00-研究/缠论知识库"

# Qdrant Collection 配置
COLLECTION_NAME = "chanlun_knowledge"
VECTOR_SIZE = 1024  # BGE-M3 输出维度为 1024

# 分块配置：按段落分块，每块最大字符数
MAX_CHUNK_CHARS = 800


class ChanlunKnowledgeSync:
    def __init__(self):
        self.qdrant_url = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
        self.embedding_url = f"http://{EMBEDDING_HOST}:{EMBEDDING_PORT}"
        self.state_file = os.path.join(KNOWLEDGE_BASE_PATH, ".sync_state.json")
        self.sync_state = self._load_state()

    # ------------------------------------------------------------------
    # 状态管理（用于增量同步）
    # ------------------------------------------------------------------
    def _load_state(self) -> dict:
        """加载同步状态，记录每个文件的 mtime 和 chunk hash"""
        if os.path.exists(self.state_file):
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_state(self):
        """保存同步状态"""
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.sync_state, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _file_hash(filepath: str) -> str:
        """计算文件内容的 MD5"""
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Qdrant 操作
    # ------------------------------------------------------------------
    def collection_exists(self) -> bool:
        """检查 Collection 是否已存在"""
        resp = requests.get(f"{self.qdrant_url}/collections/{COLLECTION_NAME}")
        return resp.status_code == 200

    def create_collection(self):
        """创建 Qdrant Collection"""
        payload = {
            "vectors": {
                "size": VECTOR_SIZE,
                "distance": "Cosine",
            }
        }
        resp = requests.put(
            f"{self.qdrant_url}/collections/{COLLECTION_NAME}",
            json=payload,
        )
        resp.raise_for_status()
        print(f"[OK] Collection '{COLLECTION_NAME}' 已创建或已存在")

    def delete_points_by_file(self, rel_path: str):
        """删除指定文件关联的所有 points（用于重新同步）"""
        resp = requests.post(
            f"{self.qdrant_url}/collections/{COLLECTION_NAME}/points/delete",
            json={
                "filter": {
                    "must": [
                        {
                            "key": "file_path",
                            "match": {"value": rel_path},
                        }
                    ]
                }
            },
        )
        resp.raise_for_status()

    def upsert_points(self, points: list):
        """批量 upsert points 到 Qdrant"""
        if not points:
            return
        resp = requests.put(
            f"{self.qdrant_url}/collections/{COLLECTION_NAME}/points",
            json={"points": points},
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # 向量嵌入
    # ------------------------------------------------------------------
    def get_embeddings(self, texts: list) -> list:
        """批量获取文本的向量嵌入（BGE-M3 /v1/embeddings 接口）"""
        payload = {
            "input": texts,
            "model": "bge-m3",
        }
        resp = requests.post(
            f"{self.embedding_url}/v1/embeddings",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # 按 index 排序确保顺序一致
        data.sort(key=lambda x: x["index"])
        return [item["embedding"] for item in data]

    # ------------------------------------------------------------------
    # 文本分块
    # ------------------------------------------------------------------
    @staticmethod
    def chunk_markdown(content: str, filepath: str) -> list:
        """
        将 Markdown 内容按段落分块。
        保留标题上下文，每个 chunk 不超过 MAX_CHUNK_CHARS 字符。
        """
        lines = content.split("\n")
        chunks = []
        current_chunk = []
        current_len = 0
        last_heading = ""

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                last_heading = stripped

            line_len = len(line) + 1

            # 如果当前块加入这行会超限，先保存当前块
            if current_len + line_len > MAX_CHUNK_CHARS and current_chunk:
                chunks.append("\n".join(current_chunk).strip())
                current_chunk = []
                current_len = 0

            current_chunk.append(line)
            current_len += line_len

        if current_chunk:
            chunks.append("\n".join(current_chunk).strip())

        return chunks

    # ------------------------------------------------------------------
    # 主同步逻辑
    # ------------------------------------------------------------------
    def sync_markdown_files(self):
        """同步所有 Markdown 文件到 Qdrant"""
        kb_path = Path(KNOWLEDGE_BASE_PATH)
        md_files = sorted(kb_path.rglob("*.md"))

        # 排除同步状态文件自身和隐藏文件
        md_files = [f for f in md_files if not f.name.startswith(".")]

        if not md_files:
            print("[WARN] 未找到任何 Markdown 文件")
            return

        # 确保 collection 存在
        pass  # Collection already exists

        total_chunks = 0
        synced_files = 0
        skipped_files = 0

        for md_file in md_files:
            rel_path = str(md_file.relative_to(kb_path))
            file_hash = self._file_hash(str(md_file))

            # 增量检查：文件未修改则跳过
            if rel_path in self.sync_state and self.sync_state[rel_path] == file_hash:
                print(f"[SKIP] {rel_path} (未修改)")
                skipped_files += 1
                continue

            # 文件已修改或新增，删除旧数据并重新索引
            content = md_file.read_text(encoding="utf-8")
            chunks = self.chunk_markdown(content, rel_path)

            if not chunks:
                print(f"[SKIP] {rel_path} (空文件)")
                skipped_files += 1
                continue

            # 删除旧 points
            self.delete_points_by_file(rel_path)

            # 批量获取嵌入
            embeddings = self.get_embeddings(chunks)

            # 构造 points
            points = []
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
                point_id = hashlib.md5(f"{rel_path}::{i}".encode()).hexdigest()
                points.append({
                    "id": point_id,
                    "vector": embedding,
                    "payload": {
                        "file_path": rel_path,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "content": chunk_text,
                    },
                })

            self.upsert_points(points)

            # 更新状态
            self.sync_state[rel_path] = file_hash
            total_chunks += len(chunks)
            synced_files += 1
            print(f"[SYNC] {rel_path} -> {len(chunks)} chunks")

        self._save_state()
        print(f"\n完成: 同步 {synced_files} 文件, 跳过 {skipped_files} 文件, 共 {total_chunks} chunks")

    # ------------------------------------------------------------------
    # 语义搜索
    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 5) -> list:
        """语义搜索：返回最相关的 chunks"""
        embedding = self.get_embeddings([query])[0]

        resp = requests.post(
            f"{self.qdrant_url}/collections/{COLLECTION_NAME}/points/search",
            json={
                "vector": embedding,
                "limit": top_k,
                "with_payload": True,
            },
        )
        resp.raise_for_status()

        results = []
        for item in resp.json()["result"]:
            payload = item["payload"]
            results.append({
                "score": item["score"],
                "file_path": payload["file_path"],
                "chunk_index": payload["chunk_index"],
                "content": payload["content"],
            })
        return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="缠论知识库 -> Qdrant 同步工具")
    parser.add_argument(
        "action",
        choices=["sync", "search"],
        help="sync: 同步知识库; search: 语义搜索",
    )
    parser.add_argument("--query", "-q", type=str, help="搜索关键词 (search 模式)")
    parser.add_argument("--top-k", "-k", type=int, default=5, help="搜索返回数量 (默认 5)")

    args = parser.parse_args()
    syncer = ChanlunKnowledgeSync()

    if args.action == "sync":
        syncer.sync_markdown_files()
    elif args.action == "search":
        if not args.query:
            print("[ERROR] search 模式需要 --query 参数")
            return
        results = syncer.search(args.query, top_k=args.top_k)
        print(f"\n搜索: \"{args.query}\" (top {args.top_k})\n")
        for i, r in enumerate(results, 1):
            print(f"--- #{i} [score={r['score']:.4f}] {r['file_path']} (chunk {r['chunk_index']}) ---")
            print(r["content"][:300])
            print()


if __name__ == "__main__":
    main()
