"""Tests for the prompt analyzer."""

from spent.analyzer import classify_prompt, recommend_model


class TestClassifyPrompt:
    def test_classification_task(self):
        messages = [{"role": "user", "content": "Classify this text as spam or not spam: 'Buy now!'"}]
        result = classify_prompt(messages)
        assert result["task_type"] == "classification"
        assert result["complexity"] <= 2

    def test_sentiment_task(self):
        messages = [{"role": "user", "content": "What is the sentiment of this review? Is it positive or negative?"}]
        result = classify_prompt(messages)
        assert result["task_type"] in ("sentiment", "classification", "yes_no")
        assert result["complexity"] <= 2

    def test_translation_task(self):
        messages = [{"role": "user", "content": "Translate this text to Spanish: Hello, how are you?"}]
        result = classify_prompt(messages)
        assert result["task_type"] == "translation"
        assert result["complexity"] == 3

    def test_coding_task(self):
        messages = [{"role": "user", "content": "Write a Python function that sorts a list of integers."}]
        result = classify_prompt(messages)
        assert result["task_type"] == "coding"
        assert result["complexity"] >= 7

    def test_summarization_task(self):
        messages = [{"role": "user", "content": "Summarize this article in two sentences."}]
        result = classify_prompt(messages)
        assert result["task_type"] == "summarization"

    def test_extraction_task(self):
        messages = [{"role": "user", "content": "Extract all email addresses from this text: contact us at a@b.com"}]
        result = classify_prompt(messages)
        assert result["task_type"] == "extraction"

    def test_reasoning_task(self):
        messages = [{"role": "user", "content": "Think through step by step: if A > B and B > C, what is the relationship between A and C?"}]
        result = classify_prompt(messages)
        assert result["task_type"] == "reasoning"
        assert result["complexity"] >= 6

    def test_generation_task(self):
        messages = [{"role": "user", "content": "Write a blog post about the future of AI in healthcare."}]
        result = classify_prompt(messages)
        assert result["task_type"] in ("generation", "coding")

    def test_empty_messages(self):
        result = classify_prompt([])
        assert result["task_type"] == "unknown"

    def test_system_messages_ignored(self):
        messages = [
            {"role": "system", "content": "You are a classifier."},
            {"role": "user", "content": "Classify this as spam or not spam."},
        ]
        result = classify_prompt(messages)
        assert result["task_type"] == "classification"

    def test_yes_no_task(self):
        messages = [{"role": "user", "content": "Is it raining? Answer with yes or no."}]
        result = classify_prompt(messages)
        assert result["task_type"] == "yes_no"
        assert result["complexity"] == 1


class TestRecommendModel:
    def test_simple_task_openai(self):
        model = recommend_model("classification", "openai")
        assert model == "gpt-4o-mini"

    def test_complex_task_openai(self):
        model = recommend_model("coding", "openai")
        assert model == "o3"

    def test_medium_task_anthropic(self):
        model = recommend_model("translation", "anthropic")
        assert model == "claude-haiku-4-5"

    def test_complex_task_anthropic(self):
        model = recommend_model("reasoning", "anthropic")
        assert model == "claude-opus-4-6"

    def test_unknown_provider(self):
        model = recommend_model("classification", "unknown_provider")
        assert model is None

    def test_generation_openai(self):
        model = recommend_model("generation", "openai")
        assert model == "gpt-4o"
