"""PR microdoc worker mode (closes ТЗ ИНТ-02 / ГЕН-06).

Consumer group on ``tasks:prdoc`` that takes a small diff snapshot, optionally
fetches RAG context for changed files from a repo's Qdrant collection, and
runs a Pydantic-AI agent to produce a Markdown summary suitable for posting
as a PR comment.
"""
