// Extracted from part-002.js
// Generic module content

            'My bad, rerouting smooth.',
        ],
    },
    orange: {
        working: [
            'Build lane hot. Let me cook.',
            'I am on turbo and still readable.',
            'Banana pro energy but disciplined.',
        ],
        break: [
            'Snack break speedrun.',
            'Lunch loop in and out.',
        ],
        socialLead: [
            'Brandon, Trey, status ping?',
            'Team, quick roast then back to work?',
        ],
        socialReply: [
            'Respectfully hilarious, now focus.',
            'Noted. Shipping anyway.',
        ],
        collision: [
            'Watch out, speed goblin incoming.',
            'Sorry, hallway drift.',
        ],
    },
    pink: {
        working: [
            'Polish pass in progress.',
            'Making this look expensive.',
            'Aligning details so it feels pro.',
        ],
        break: [
            'Resetting eyes for pixel-perfect pass.',
            'Quick tea and aesthetic recalibration.',
        ],
        socialLead: [
            'Can we align visual language real quick?',
            'Need one clean second opinion.',
        ],
        socialReply: [
            'Yep, that composition is better.',
            'Agreed. Keep it purposeful.',
        ],
        collision: [
            'Oops, sorry, wardrobe malfunction.',
            'Tiny crash, no drama.',
        ],
    },
    purple: {
        working: [
            'Deep work pod mode active.',
            'Threading context with zero panic.',
            'Strategic pass underway.',
        ],
        break: [
            'Micro-break for macro clarity.',
            'Lunch room strategy huddle.',
        ],
        socialLead: [
            'Can we map priorities in 20 seconds?',
            'Need a fast alignment check.',
        ],
        socialReply: [
            'Priority order looks strong.',
            'Yep, sequence is correct.',
        ],
        collision: [
            'Excuse me, merging left.',
            'Sorry, traffic math failed me.',
        ],
    },
    yellow: {
        working: [
            'Support lane warm and responsive.',
            'Handling tickets with empathy and speed.',
            'Status updates queued and clear.',
        ],
        break: [
            'Coffee with customer context.',
            'Quick reset, then support sweep.',
        ],
        socialLead: [
            'Need help triaging this queue?',
            'Anyone free for a fast handoff?',
        ],
        socialReply: [
            'Yep, I can cover that.',
            'Good handoff, thanks.',
        ],
        collision: [
            'Whoops, pardon me.',
            'Sorry, crowding there.',
        ],
    },
    default: {
        working: OFFICE_DIALOGUE.working,
        break: OFFICE_DIALOGUE.break,
        socialLead: ['Quick sync?', 'Any updates?'],
        socialReply: ['Sounds good.', 'Copy that.'],
        collision: OFFICE_DIALOGUE.collision,
    },
};

// ── Chat Robot Status Sayings ──
const CHAT_ROBOT_SAYINGS = {
    thinking: [
        'Spinning up robots...',
        'Beep boop beep...',
        'Consulting the hive mind...',
        'Warming up neurons...',
        'Loading clever thoughts...',
        'Connecting synapses...',
        'Brewing fresh ideas...',
        'Calibrating brain waves...',
        'Pondering possibilities...',
        'Initializing thought engine...',
    ],
    working: [
        'Building something cool...',
        'Robots are on it...',
        'Turbo mode engaged...',
        'Compiling awesomeness...',
        'Making magic happen...',
        'Crunching the numbers...',
        'Assembling the pieces...',
        'Putting it all together...',
        'Almost there, hang tight...',
        'Cooking up a response...',
    ],
};

// Tool name → human-friendly description
const CHAT_TOOL_DESCRIPTIONS = {
    'fs.read_file':           'Reading files...',
    'fs.write_file':          'Writing code...',
    'fs.list_dir':            'Browsing directories...',
    'fs.search':              'Searching files...',
    'code.search':            'Searching codebase...',
    'code.find_definition':   'Finding definitions...',
    'code.find_references':   'Finding references...',
    'code.project_structure': 'Mapping project structure...',
    'shell.exec':             'Running a command...',
    'git.status':             'Checking git status...',
    'git.log':                'Reading git history...',
    'git.diff':               'Reviewing changes...',
    'git.commit':             'Committing changes...',
    'git.blame':              'Checking git blame...',
    'browser.open':           'Opening a page...',
    'browser.click':          'Clicking around...',
    'browser.type':           'Typing in browser...',
    'browser.screenshot':     'Taking a screenshot...',
    'browser.extract':        'Extracting page data...',
    'browser.close':          'Closing browser...',
    'diff.create':            'Preparing a diff...',
    'diff.preview':           'Previewing changes...',
    'diff.apply_patch':       'Applying changes...',
    'email.send':             'Sending email...',
    'email.reply':            'Replying to email...',
    'email.read':             'Reading email...',
    'email.get':              'Fetching email...',
    'calendar.today':         'Checking calendar...',
    'calendar.week':          'Checking schedule...',
    'calendar.create_event':  'Creating event...',
    'calendar.suggest_times': 'Finding free times...',
    'db.query':               'Querying database...',
    'db.schema':              'Reading schema...',
    'db.connections':         'Checking connections...',
    'rag.search':             'Searching knowledge base...',
};
// Prefix fallbacks for tool families
const CHAT_TOOL_PREFIX_MAP = {
    'fs.':       'Working with files...',
    'code.':     'Analyzing code...',
    'git.':      'Checking git...',
    'browser.':  'Browsing the web...',
    'diff.':     'Preparing changes...',
    'email.':    'Handling email...',
    'calendar.': 'Checking calendar...',
    'db.':       'Querying database...',
};
function describeToolName(toolName) {
    const name = (toolName || '').trim();