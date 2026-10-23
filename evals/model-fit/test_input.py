"""Model Fit hook regression checks."""

from unittest.mock import patch

from hook_case import AUTO, INPUT, STATE, AutoSwitchCase


class InputPreservationTests(AutoSwitchCase):
    def test_queue_requires_target_profile_and_matching_turn(self):
        path = self.stage()
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}
            }
            with self.assertRaisesRegex(ValueError, "Target profile"):
                AUTO.enqueue(self.thread_id, self.turn_id)
            self.assertEqual(app.call.call_count, 1)
        self.assertEqual(STATE.read_state(path)["phase"], "ready")
        with self.assertRaisesRegex(ValueError, "No matching"):
            AUTO.enqueue(self.thread_id, "other-turn")
        self.assertEqual(STATE.read_state(path)["phase"], "ready")

    def test_queue_runs_once_and_drops_prompt_from_state(self):
        path = self.stage()
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.queue_receipt(),
            ]
            self.assertEqual(
                AUTO.enqueue(self.thread_id, self.turn_id)["status"], "queued"
            )
            queued_prompt = app.call.call_args_list[2].args[1]["input"][0]["text"]
            self.assertTrue(
                queued_prompt.startswith(self.prompt + "\n\n<!-- model-fit-replay:")
            )
        state = STATE.read_state(path)
        self.assertEqual(state["phase"], "queued")
        self.assertEqual(
            state["queued_prompt_digest"], INPUT.prompt_digest(queued_prompt)
        )
        self.assertNotIn("prompt", state)
        with patch.object(AUTO, "AppServerReader") as reader:
            self.assertEqual(
                AUTO.enqueue(self.thread_id, self.turn_id),
                {
                    "queued_submission_id": "queued-1",
                    "status": "already_queued",
                },
            )
            reader.assert_not_called()

    def test_queue_preserves_all_native_input_and_text_spans(self):
        path = self.stage()
        content = [
            {
                "type": "text",
                "text": self.prompt,
                "text_elements": [
                    {"byteRange": {"start": 0, "end": 4}, "placeholder": "ref"}
                ],
            },
            {
                "type": "image",
                "url": "data:image/png;base64,aW1hZ2U=",
                "detail": "original",
            },
            {"type": "localImage", "path": "/tmp/screenshot.png"},
            {"type": "audio", "url": "data:audio/wav;base64,YXVkaW8="},
            {"type": "localAudio", "path": "/tmp/voice.wav"},
            {
                "type": "mention",
                "name": "screencast.mov",
                "path": "/tmp/screencast.mov",
            },
            {
                "type": "skill",
                "name": "model-fit",
                "path": "/tmp/skills/model-fit/SKILL.md",
            },
        ]
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt(content),
            ]
            AUTO.enqueue(self.thread_id, self.turn_id)
            queued = app.call.call_args_list[-1].args[1]["input"]
        self.assertEqual(queued[1:], content[1:])
        self.assertEqual(queued[0]["text_elements"], content[0]["text_elements"])
        self.assertEqual(content[0]["text"], self.prompt)
        self.assertTrue(
            queued[0]["text"].startswith(self.prompt + "\n\n<!-- model-fit-replay:")
        )
        state = STATE.read_state(path)
        self.assertEqual(state["source_input_digest"], INPUT.input_digest(content))
        self.assertEqual(state["queued_input_digest"], INPUT.input_digest(queued))
        self.assertNotIn("data:image", path.read_text())
        self.assertNotIn("screenshot.png", path.read_text())

    def test_native_local_images_are_accepted_and_canonical_digest_is_saved(self):
        path = self.stage()
        content = [{"type": "text", "text": self.prompt}] + [
            {"type": "localImage", "path": f"/tmp/image-{n}.jpeg", "detail": None}
            for n in range(5)
        ]
        native = [
            {"type": "text", "text": INPUT.replay_prompt(self.prompt, "nonce")}
        ] + [
            {
                "type": "image",
                "url": f"data:image/jpeg;base64,aW1hZ2U{n}",
                "detail": None,
            }
            for n in range(5)
        ]
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                {"queuedSubmission": {"id": "queued-1", "input": native}},
            ]
            self.assertEqual(
                AUTO.enqueue(self.thread_id, self.turn_id)["status"], "queued"
            )
            self.assertNotIn(
                "thread/queue/delete",
                [call.args[0] for call in app.call.call_args_list],
            )
        state = STATE.read_state(path)
        self.assertEqual(state["source_input_digest"], INPUT.input_digest(content))
        self.assertEqual(state["queued_input_digest"], INPUT.input_digest(native))
        self.assertNotIn("base64", path.read_text())

    def test_native_image_conversion_keeps_metadata_and_other_input_exact(self):
        original = [
            {"type": "text", "text": "request", "text_elements": []},
            {"type": "localImage", "path": "/tmp/image.png", "detail": "original"},
        ]
        native = [
            original[0],
            {
                "type": "image",
                "url": "data:image/png;base64,aW1hZ2U=",
                "detail": "original",
            },
        ]
        self.assertTrue(INPUT.queue_input_matches(original, native))
        for changed in [
            native[:1],
            [{"type": "text", "text": "changed", "text_elements": []}, native[1]],
            [native[0], dict(native[1], detail="low")],
            [native[0], dict(native[1], url="data:image/png;base64,")],
            [native[0], dict(native[1], url="https://example.org/image.png")],
        ]:
            with self.subTest(changed=changed):
                self.assertFalse(INPUT.queue_input_matches(original, changed))

    def test_direct_image_payload_change_is_still_rejected(self):
        original = [{"type": "image", "url": "data:image/png;base64,b3JpZ2luYWw="}]
        self.assertFalse(
            INPUT.queue_input_matches(
                original,
                [{"type": "image", "url": "data:image/png;base64,Y2hhbmdlZA=="}],
            )
        )

    def test_input_without_text_keeps_attachments_and_gets_replay_marker(self):
        path = self.stage()
        state = STATE.read_state(path)
        state["prompt"] = ""
        STATE.write_state(path, state)
        content = [
            {"type": "image", "url": "data:image/png;base64,aW1hZ2U=", "detail": None}
        ]
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt(content),
            ]
            AUTO.enqueue(self.thread_id, self.turn_id)
            queued = app.call.call_args_list[-1].args[1]["input"]
        self.assertEqual(queued[0], content[0])
        self.assertEqual(queued[1]["type"], "text")
        self.assertIn("<!-- model-fit-replay:", queued[1]["text"])

    def test_missing_or_mismatched_source_never_queues_partial_input(self):
        for response in [
            {"data": [], "nextCursor": None},
            self.source_response([{"type": "text", "text": "Другое поручение"}]),
        ]:
            with self.subTest(response=response):
                path = self.stage()
                with patch.object(AUTO, "AppServerReader") as reader:
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        response,
                    ]
                    with self.assertRaisesRegex(ValueError, "Source user input"):
                        AUTO.enqueue(self.thread_id, self.turn_id)
                    self.assertNotIn(
                        "thread/queue/add", [c.args[0] for c in app.call.call_args_list]
                    )
                self.assertEqual(STATE.read_state(path)["phase"], "ready")

    def test_replay_preserves_order_and_appends_only_to_last_text(self):
        content = [
            {"type": "text", "text": "Первая часть", "text_elements": []},
            {"type": "image", "url": "data:image/png;base64,aW1hZ2U="},
            {"type": "text", "text": "Вторая часть", "text_elements": []},
            {"type": "mention", "name": "clip.mov", "path": "/tmp/clip.mov"},
        ]
        replay = INPUT.replay_input(content, "nonce")
        self.assertEqual(replay[:2], content[:2])
        self.assertEqual(replay[3], content[3])
        self.assertEqual(replay[2]["text_elements"], content[2]["text_elements"])
        self.assertEqual(
            replay[2]["text"], INPUT.replay_prompt("Вторая часть", "nonce")
        )

    def test_source_input_follows_native_pagination(self):
        content = [{"type": "image", "url": "data:image/png;base64,aW1hZ2U="}]
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": "next"},
                self.source_response(content),
            ]
            self.assertEqual(
                AUTO.source_input(app, self.thread_id, self.turn_id), content
            )
            self.assertEqual(app.call.call_args_list[-1].args[1]["cursor"], "next")
