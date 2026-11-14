"""A storage event must not replace the job that owns a live queued bubble."""

import subprocess
from pathlib import Path


def queue_driver(root):
    source = (root / "tests/test_a_queued_message_is_never_lost.py").read_text(encoding="utf-8")
    return source.split('DRIVER = r"""', 1)[1].split('"""', 1)[0]


CROSS_CHAT_FAILURE_CASES = r"""
  records.clear(); p = page(false); p.put('A failed send');
  p.state.streaming = false; assert.equal(p.queue.drainQueued(), true);
  p.sends[0].files.onFailed('Network error'); p.state.streaming = false;
  assert.equal(p.queue.drainQueued(), false, 'a failed job waits for Send now');
  assert.equal(saved('A')[0].text, 'A failed send');
  assert.equal(saved('A')[0].retryRequired, true, 'failed job remains marked for manual retry');
  await p.session.selectChat('B');
  p.state.streaming = true; p.put('B after successful reply');
  p.ctx.window.ThomasChatModelSelection = {ensureCurrent: () => true};
  p.ctx.window.ThomasCodingAgentPicker = {effective: () => ''};
  p.ctx.window.ThomasChatStreamConsumer = {
    createTextPainter: paint => ({paint, settle() {}}), consume: async () => {},
  };
  p.ctx.AbortController = AbortController;
  p.ctx.fetch = async () => ({ok: true});
  p.state.dials = {autonomy: 1, fileAccess: 'none', guardrails: 'standard', effort: 'low', memory: false};
  vm.runInContext(source('chat_stream_actions.js'), p.ctx);
  const flowB = p.ctx.window.ThomasChatStreamActions.create({...p.deps, turnFlow: p.queue,
    captureConversation: () => () => true, setExternalBusy() {}, ensureSession: async () => 'B-session',
    updateStreamingBubble() {}, renderActivity() {}, canvasDocumentDone() {}, refreshChats() {},
    maybePromptChatGPTConnection: async () => {}});
  await flowB.streamReal('B succeeds');
  assert.equal(p.sends.at(-1)?.chat, 'B', 'B drains after its successful reply despite A failing');
  assert.equal(p.sends.at(-1)?.text, 'B after successful reply');
  assert.equal(saved('B').length, 1, 'B copy remains until its send is accepted');
  assert.equal(saved('A')[0].text, 'A failed send', 'A failed job remains stored');
  await p.session.selectChat('A'); p.state.streaming = false;
  assert.equal(p.queue.drainQueued(), false, 'A failed job still requires Send now');
  assert.match(p.notes()[0].textContent, /Send failed/, 'restored failure shows a reason');
  p.button(p.notes()[0], 'Send now').click();
  assert.equal(p.sends.at(-1)?.text, 'A failed send', 'manual retry can still send A');
  assert.equal(saved('A')[0].retryRequired, true, 'claim retains the retry guard until acceptance');
"""


STORAGE_EVENT_CASES = r"""
  records.clear(); p = page(false); p.put('idle kept');
  const idleNote = p.notes()[0], idleBubble = p.refs.at(-1).wrapEl;
  const remote = {id: 'remote-row', text: 'from other tab', docs: [], images: [],
    selection: {modelId: 'old', modelLabel: 'Old model'}};
  storage.setItem(key('A'), JSON.stringify([...saved('A'), remote]));
  p.events.storage({key: key('A')});
  assert.equal(p.notes().length, 2, 'one note per stored job after an idle storage event');
  assert.equal(p.notes()[0], idleNote, 'existing note and its buttons stay live');
  assert.equal(p.refs.at(-2).wrapEl, idleBubble, 'existing bubble is not redrawn');
  assert.equal(p.state.messages.filter(m => m.text === 'idle kept').length, 1);
  assert.equal(p.state.messages.filter(m => m.text === 'from other tab').length, 1);
  storage.setItem(key('A'), JSON.stringify(saved('A').filter(row => row.id !== remote.id)));
  p.events.storage({key: key('A')});
  assert.equal(p.notes().length, 1, 'remote removal removes the whole remote row');
  assert.equal(p.state.messages.filter(m => m.text === 'from other tab').length, 0);
  p.button(idleNote, 'Remove').click();
  assert.equal(saved('A').length, 0, 'the original note still has a live Remove button');
  records.clear(); p = page(false); p.put('in flight');
  p.state.streaming = false; assert.equal(p.queue.drainQueued(), true);
  const sentNote = p.notes()[0], sentBubble = p.refs.at(-1).wrapEl;
  assert.equal(saved('A').length, 1, 'claim retains the stored copy');
  storage.setItem(key('A'), JSON.stringify([...saved('A'), remote]));
  p.events.storage({key: key('A')});
  assert.equal(p.notes().length, 2, 'no duplicate note while first job is sending');
  assert.equal(p.notes()[0], sentNote, 'sending job keeps its note');
  assert.equal(p.refs.at(-2).wrapEl, sentBubble, 'sending job keeps its bubble');
  assert.equal(p.state.messages.filter(m => m.text === 'in flight').length, 1);
  p.sends[0].files.onAccepted();
  assert.deepEqual(saved('A').map(row => row.id), [remote.id],
    'accepted job is removed from storage after the storage event');
  assert.equal(p.notes().length, 1, 'only the other tab job remains queued');
  p.state.streaming = false; assert.equal(p.queue.drainQueued(), true);
  assert.equal(p.sends[1].text, 'from other tab', 'accepted job is never sent a second time');
"""


def test_storage_event_reconciles_idle_and_in_flight_jobs():
    root = Path(__file__).resolve().parents[1]
    driver = queue_driver(root).replace(
        "  console.log('queue persistence, conversation ownership",
        STORAGE_EVENT_CASES + "  console.log('queue persistence, conversation ownership",
    )
    result = subprocess.run(
        ["node", "-e", driver, str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_job_in_chat_a_does_not_block_successful_chat_b_reply():
    root = Path(__file__).resolve().parents[1]
    driver = queue_driver(root).replace(
        "  console.log('queue persistence, conversation ownership",
        CROSS_CHAT_FAILURE_CASES + "  console.log('queue persistence, conversation ownership",
    )
    result = subprocess.run(
        ["node", "-e", driver, str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
