from django.db.models import Q
from apps.learning.models import Article, Topic, Category


class KnowledgeService:
    """
    FR-005 Weighted Knowledge Retrieval Service for CAGH AI Assistant (Phase 1).
    Ranks published educational articles from apps.learning database
    using a weighted relevance scoring system:
    - Title match: +5 points
    - Topic match: +4 points
    - Category match: +3 points
    - Summary match: +2 points
    - Content body match: +1 point
    """

    @classmethod
    def retrieve_context(cls, query_text: str, max_articles: int = 3) -> str:
        if not query_text or len(query_text.strip()) < 3:
            return ""

        query_terms = [t.strip().lower() for t in query_text.split() if len(t.strip()) > 3]
        if not query_terms:
            query_terms = [query_text.strip().lower()]

        # Filter published articles
        published_articles = Article.objects.filter(status=Article.ArticleStatus.PUBLISHED).select_related('topic', 'topic__category')
        if not published_articles.exists():
            return ""

        scored_articles = []
        for art in published_articles:
            score = 0
            title_lower = art.title.lower()
            summary_lower = art.summary.lower()
            content_lower = art.content.lower()
            topic_name_lower = art.topic.name.lower() if art.topic else ""
            category_name_lower = art.topic.category.name.lower() if (art.topic and art.topic.category) else ""

            for term in query_terms:
                if term in title_lower:
                    score += 5
                if term in topic_name_lower:
                    score += 4
                if term in category_name_lower:
                    score += 3
                if term in summary_lower:
                    score += 2
                if term in content_lower:
                    score += 1

            if score > 0:
                scored_articles.append((score, art))

        # Sort by score descending
        scored_articles.sort(key=lambda x: x[0], reverse=True)
        top_articles = [art for score, art in scored_articles[:max_articles]]

        # Fallback to recent published articles if no term matched
        if not top_articles:
            top_articles = list(published_articles.order_by('-published_at')[:max_articles])

        context_snippets = []
        for art in top_articles:
            snippet = f"--- Approved CAGH Guide: {art.title} ---\nSummary: {art.summary}\nContent: {art.content[:400]}..."
            if art.key_takeaway_tip:
                snippet += f"\nKey Tip: {art.key_takeaway_tip}"
            context_snippets.append(snippet)

        return "\n\n".join(context_snippets)
