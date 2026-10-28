import json
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .ai import AIServiceError, _provider_config, stream_chat_completion
from .models import (
    ChatMessage,
    Destination,
    RegionalDishSuggestion,
    SavedTrip,
    TouristProfile,
    TripStop,
)


class ChatStreamingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="stream-tourist", password="test-password")
        TouristProfile.objects.create(user=self.user)
        destination = Destination.objects.create(
            name="Fort Kochi",
            category="culture",
            region="Kerala",
            latitude=9.9659,
            longitude=76.2413,
        )
        RegionalDishSuggestion.objects.create(
            region="Kerala",
            name="Appam",
            description="A regional dish idea.",
        )
        trip = SavedTrip.objects.create(tourist=self.user, title="Kerala visit")
        TripStop.objects.create(
            trip=trip,
            stop_type="destination",
            destination=destination,
            name=destination.name,
            sequence=0,
        )
        self.client.force_login(self.user)

    @patch("core.views.stream_chat_completion")
    def test_chat_streams_representative_questions_and_persists_history(self, stream_completion):
        stream_completion.side_effect = [
            iter(("Compare the route ", "options.")),
            iter(("Fort Kochi is ", "a cultural destination.")),
            iter(("Appam is a regional ", "suggestion, not a menu guarantee.")),
        ]
        questions = (
            "How should I travel from Kochi to Munnar?",
            "What should I see in Kerala?",
            "Suggest local Kerala food.",
        )

        for question in questions:
            response = self.client.post(
                reverse("chatbot"),
                {"prompt": question},
                HTTP_ACCEPT="text/event-stream",
            )
            self.assertTrue(response.streaming)
            self.assertTrue(response["Content-Type"].startswith("text/event-stream"))
            events = iter(response.streaming_content)
            first = next(events).decode("utf-8")
            self.assertEqual(json.loads(first.removeprefix("data: ").strip())["type"], "token")
            remaining = "".join(chunk.decode("utf-8") for chunk in events)
            self.assertIn('"type":"done"', remaining)

        saved_messages = list(ChatMessage.objects.order_by("pk"))
        self.assertEqual(len(saved_messages), 6)
        self.assertEqual([message.sender for message in saved_messages], ["user", "bot"] * 3)
        self.assertTrue(
            saved_messages[-1].content.endswith(
                "Would you prefer a particular meal or dietary style for food in Kerala?"
            )
        )
        last_messages = stream_completion.call_args_list[-1].args[0]
        self.assertIn("exactly one useful, specific follow-up question", last_messages[0]["content"])
        self.assertIn("regional_dish_suggestions", last_messages[1]["content"])
        self.assertIn("Kerala visit", last_messages[1]["content"])
        self.assertTrue(response["X-Accel-Buffering"] == "no")

    @patch("core.views.stream_chat_completion", side_effect=AIServiceError("Groq is rate-limiting requests. Wait and try again."))
    def test_streamed_provider_error_is_helpful_and_persisted(self, mock_stream):
        response = self.client.post(reverse("chatbot"), {"prompt": "Suggest a short trip."})
        events = "".join(chunk.decode("utf-8") for chunk in response.streaming_content)
        self.assertIn('"type":"error"', events)
        self.assertIn("rate-limiting", events)
        self.assertNotIn("Traceback", events)
        self.assertEqual(ChatMessage.objects.filter(sender="bot").get().content, "Groq is rate-limiting requests. Wait and try again.")
        mock_stream.assert_called_once()

    @override_settings(
        AI_PROVIDER="groq",
        GROQ_API_KEY="test-groq-key",
        GROQ_MODEL="openai/gpt-oss-20b",
        OPENROUTER_API_KEY="test-openrouter-key",
    )
    @patch("core.ai._http_session")
    def test_groq_uses_official_endpoint_and_streams_tokens(self, get_session):
        session = get_session.return_value
        response_context = MagicMock()
        response = response_context.__enter__.return_value
        response.iter_lines.return_value = [
            b'data: {"choices":[],"usage":{"total_tokens":12}}',
            b'data: {"choices":[{"delta":{"content":"Kochi \xe2\x86\x92 "}}]}',
            b'data: {"choices":[{"delta":{"content":"Delhi"}}]}',
            b"data: [DONE]",
        ]
        session.post.return_value = response_context

        tokens = list(stream_chat_completion([{"role": "user", "content": "Plan a trip."}]))

        self.assertEqual(tokens, ["Kochi → ", "Delhi"])
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-groq-key")
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["json"]["max_completion_tokens"], 256)
        self.assertEqual(kwargs["json"]["reasoning_effort"], "low")
        response.iter_lines.assert_called_once_with(decode_unicode=False)

    @override_settings(
        AI_PROVIDER="openrouter",
        OPENROUTER_API_KEY="test-openrouter-key",
        OPENROUTER_MODEL="openrouter/auto",
    )
    @patch("core.ai._http_session")
    def test_openrouter_allows_reasoning_and_text_in_output_budget(self, get_session):
        response_context = MagicMock()
        response = response_context.__enter__.return_value
        response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"reasoning":"brief reasoning"}}]}',
            b'data: {"choices":[{"delta":{"content":"Helpful reply."}}]}',
            b"data: [DONE]",
        ]
        get_session.return_value.post.return_value = response_context

        tokens = list(stream_chat_completion([{"role": "user", "content": "Plan a trip."}]))

        self.assertEqual(tokens, ["Helpful reply."])
        payload = get_session.return_value.post.call_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], 1024)
        self.assertEqual(payload["reasoning_effort"], "none")

    @patch("core.views.stream_chat_completion")
    def test_greeting_and_food_follow_up_get_local_contextual_replies(self, stream_completion):
        response = self.client.post(reverse("chatbot"), {"prompt": "hi"})
        greeting = "".join(
            event.get("text", "")
            for event in (
                json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
                for chunk in response.streaming_content
            )
            if event["type"] == "token"
        )
        self.assertIn("Hi! I can help you plan routes", greeting)
        self.assertTrue(greeting.endswith("What city or region would you like to explore?"))

        conversation = ChatMessage.objects.filter(sender="bot").get().conversation
        ChatMessage.objects.filter(conversation=conversation, sender="bot").update(
            content="Would you like food recommendations somewhere in Kerala?"
        )
        ChatMessage.objects.create(
            conversation=conversation,
            sender="bot",
            content="OpenRouter returned an invalid response.",
        )
        response = self.client.post(reverse("chatbot"), {"prompt": "food"})
        food_reply = "".join(
            event.get("text", "")
            for event in (
                json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
                for chunk in response.streaming_content
            )
            if event["type"] == "token"
        )

        self.assertIn("regional food ideas for Kerala are Appam", food_reply)
        self.assertTrue(food_reply.endswith("Do you prefer vegetarian options or a particular meal?"))
        self.assertFalse(stream_completion.called)
        self.assertEqual(
            ChatMessage.objects.filter(conversation=conversation, sender="bot").count(),
            3,
        )

    @patch("core.views.stream_chat_completion", return_value=iter(("I can help plan this route.",)))
    def test_route_prompt_context_uses_mentioned_regions_not_substring_matches(self, stream_completion):
        Destination.objects.create(
            name="Tripura Palace",
            category="culture",
            region="Tripura",
            latitude=23.8315,
            longitude=91.2868,
            best_for="heritage",
        )
        Destination.objects.create(
            name="Red Fort",
            category="history",
            region="Delhi",
            latitude=28.6562,
            longitude=77.2410,
            best_for="heritage",
        )

        response = self.client.post(
            reverse("chatbot"),
            {"prompt": "plan a trip from Kerala to Delhi"},
        )
        list(response.streaming_content)

        chat_messages = stream_completion.call_args.args[0]
        context = json.loads(chat_messages[1]["content"].removeprefix("Application data: "))
        regions = {destination["region"] for destination in context["destinations"]}
        destination_names = {destination["name"] for destination in context["destinations"]}
        self.assertIn("Kerala", regions)
        self.assertIn("Delhi", regions)
        self.assertNotIn("Tripura", regions)
        self.assertNotIn("Tripura Palace", destination_names)

    @override_settings(AI_PROVIDER="groq", GROQ_API_KEY="", OPENROUTER_API_KEY="fallback-key")
    def test_openrouter_is_used_only_as_configuration_fallback(self):
        provider, key, model, endpoint = _provider_config()
        self.assertEqual(provider, "openrouter")
        self.assertEqual(key, "fallback-key")
        self.assertEqual(model, "openrouter/auto")
        self.assertEqual(endpoint, "https://openrouter.ai/api/v1/chat/completions")

    @override_settings(AI_PROVIDER="groq", GROQ_API_KEY="test-groq-key", OPENROUTER_API_KEY="")
    @patch("core.ai._http_session")
    def test_groq_rate_limit_returns_a_safe_retry_message(self, get_session):
        session = get_session.return_value
        response_context = MagicMock()
        response = response_context.__enter__.return_value
        provider_error = requests.Response()
        provider_error.status_code = 429
        response.raise_for_status.side_effect = requests.HTTPError(response=provider_error)
        session.post.return_value = response_context

        with self.assertRaises(AIServiceError) as caught:
            list(stream_chat_completion([{"role": "user", "content": "Hello"}]))

        self.assertIn("rate-limiting", str(caught.exception))
        self.assertNotIn("429", str(caught.exception))

    @override_settings(AI_PROVIDER="openrouter", OPENROUTER_API_KEY="test-key")
    @patch("core.ai._http_session")
    def test_openrouter_stream_errors_are_reported_without_provider_payload(self, get_session):
        response_context = MagicMock()
        response = response_context.__enter__.return_value
        response.iter_lines.return_value = [
            b'data: {"error":{"code":"no_endpoints","message":"provider diagnostic"}}',
        ]
        get_session.return_value.post.return_value = response_context

        with self.assertRaises(AIServiceError) as caught:
            list(stream_chat_completion([{"role": "user", "content": "Suggest food."}]))

        self.assertIn("Openrouter could not complete this request", str(caught.exception))
        self.assertNotIn("provider diagnostic", str(caught.exception))

    @override_settings(AI_PROVIDER="openrouter", OPENROUTER_API_KEY="test-key")
    @patch("core.ai._http_session")
    def test_openrouter_reasoning_only_response_has_helpful_error(self, get_session):
        response_context = MagicMock()
        response = response_context.__enter__.return_value
        response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"reasoning":"reasoning only"}}]}',
            b"data: [DONE]",
        ]
        get_session.return_value.post.return_value = response_context

        with self.assertRaises(AIServiceError) as caught:
            list(stream_chat_completion([{"role": "user", "content": "Suggest food."}]))

        self.assertIn("completed without a text reply", str(caught.exception))

    @override_settings(AI_PROVIDER="groq", GROQ_API_KEY="test-groq-key", OPENROUTER_API_KEY="")
    @patch("core.ai._http_session")
    def test_groq_timeout_returns_a_safe_retry_message(self, get_session):
        get_session.return_value.post.side_effect = requests.Timeout("timed out")

        with self.assertRaises(AIServiceError) as caught:
            list(stream_chat_completion([{"role": "user", "content": "Hello"}]))

        self.assertIn("Could not connect to Groq", str(caught.exception))
        self.assertNotIn("timed out", str(caught.exception))

    @override_settings(AI_PROVIDER="groq", GROQ_API_KEY="must-not-leak", OPENROUTER_API_KEY="")
    @patch("core.ai._http_session")
    def test_invalid_groq_key_error_does_not_expose_credentials(self, get_session):
        session = get_session.return_value
        response_context = MagicMock()
        response = response_context.__enter__.return_value
        provider_error = requests.Response()
        provider_error.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError(response=provider_error)
        session.post.return_value = response_context

        with self.assertRaises(AIServiceError) as caught:
            list(stream_chat_completion([{"role": "user", "content": "Hello"}]))

        self.assertIn("GROQ_API_KEY", str(caught.exception))
        self.assertNotIn("must-not-leak", str(caught.exception))
