/* One translation of the steer endpoint's answers into words a person can act
   on. Two surfaces carry a steer box for a running task -- the Work task card
   (unified_work_support.js, sent by unified_work_mode_steer.js) and the chat activity
   card (chat_activity_view.js, sent by chat_activity_actions.js) -- and each
   used to word refusals its own way. The chat one answered EVERY failure with
   "Couldn't reach the running task just now.", which claims a network problem
   for a task that had simply already finished, and threw away the reason the
   server actually sent. Both now read the same table, so the same refusal
   cannot come out as two different explanations.

   The vocabulary is the endpoint's: chat_v2_session_routes.py answers
   session_mismatch / invalid_reference / empty_message, and the ledger
   (task_bot_runtime.steer_execution) answers with a sentence naming a raw
   execution id. None of those are for reading. */
(function () {
  'use strict';

  const KNOWN = {
    session_mismatch: 'This task belongs to a different conversation.',
    invalid_reference: 'Thomas could not tell which task this update was for.',
    empty_message: 'Type what you want changed before sending the update.',
    not_found: 'Thomas has no record of this task any more.',
  };

  function failureText(reason) {
    const raw = String(reason || '').trim();
    if (KNOWN[raw]) return KNOWN[raw];
    if (/^No running task matches reference/i.test(raw)) return 'This task is no longer running, so it cannot take an update.';
    // An HTTP status is not a sentence either, and it is what a proxy or a
    // restarted server leaves behind.
    if (/^HTTP \d+$/.test(raw)) return 'Thomas could not be reached just now.';
    return raw || 'Thomas could not be reached.';
  }

  window.ThomasSteering = { failureText };
})();
