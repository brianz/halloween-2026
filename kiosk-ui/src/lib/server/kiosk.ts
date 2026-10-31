import { spawn, type ChildProcessByStdio } from 'node:child_process';
import path from 'node:path';
import type { Readable } from 'node:stream';
import { fileURLToPath } from 'node:url';

// stdin is 'ignore' (null), stdout/stderr are piped — matches the spawn()
// call below.
type KioskProcess = ChildProcessByStdio<null, Readable, Readable>;

// This file lives at kiosk-ui/src/lib/server/kiosk.ts — walk up to the repo
// root (halloween-pirates/) rather than trusting process.cwd(), since that
// depends on where `npm run dev` happens to be invoked from.
const here = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(here, '..', '..', '..', '..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const SCRIPT = path.join(REPO_ROOT, 'pirate_riddle_kiosk.py');

const MAX_LOG_LINES = 400;

type KioskState = {
	process: KioskProcess | null;
	log: string[];
	startedAt: number | null;
	difficulty: number | null;
};

// Module-level singleton. This dev server is the only thing driving the
// kiosk, and only one kid's session runs at a time by the project's own
// design ("one process per kid" — see CLAUDE.md), so there's nothing to
// key this by. Note: editing this file while a game is running triggers
// Vite's module reload and loses track of `process` here (the actual OS
// process keeps running regardless) — don't do that; use
// `just kill-riddle-kiosk` or Activity Monitor to recover if it happens.
const state: KioskState = {
	process: null,
	log: [],
	startedAt: null,
	difficulty: null
};

function appendLog(chunk: string): void {
	for (const line of chunk.split('\n')) {
		if (line.length === 0) continue;
		state.log.push(line);
	}
	if (state.log.length > MAX_LOG_LINES) {
		state.log.splice(0, state.log.length - MAX_LOG_LINES);
	}
}

function clearProcessState(): void {
	state.process = null;
	state.startedAt = null;
	state.difficulty = null;
}

export function isRunning(): boolean {
	return state.process !== null;
}

export function getStatus() {
	return {
		running: isRunning(),
		difficulty: state.difficulty,
		startedAt: state.startedAt,
		log: state.log
	};
}

export type ActionResult = { ok: true } | { ok: false; error: string };

export function startKiosk(difficulty: number): ActionResult {
	if (state.process !== null) {
		return { ok: false, error: 'A session is already running.' };
	}
	if (!Number.isInteger(difficulty) || difficulty < 1 || difficulty > 10) {
		return { ok: false, error: 'Difficulty must be a whole number from 1 to 10.' };
	}

	let child: KioskProcess;
	try {
		child = spawn(PYTHON, ['-u', SCRIPT, '--difficulty', String(difficulty)], {
			// -u: Python fully block-buffers stdout when it's not a TTY (i.e.
			// always, once piped like this), so without it the log below would
			// only show up in one big dump at process exit instead of live.
			cwd: REPO_ROOT,
			stdio: ['ignore', 'pipe', 'pipe']
		});
	} catch (err) {
		return { ok: false, error: err instanceof Error ? err.message : String(err) };
	}

	state.process = child;
	state.startedAt = Date.now();
	state.difficulty = difficulty;
	state.log = [];
	appendLog(`$ pirate_riddle_kiosk.py --difficulty ${difficulty}  (pid ${child.pid})`);

	child.stdout.on('data', (chunk: Buffer) => appendLog(chunk.toString('utf8')));
	child.stderr.on('data', (chunk: Buffer) => appendLog(chunk.toString('utf8')));

	child.on('exit', (code, signal) => {
		appendLog(`[process exited — code=${code} signal=${signal}]`);
		clearProcessState();
	});

	child.on('error', (err) => {
		appendLog(`[failed to start: ${err.message}]`);
		clearProcessState();
	});

	return { ok: true };
}

export function endGracefully(): ActionResult {
	if (state.process === null) {
		return { ok: false, error: 'No session is running.' };
	}
	// The exact signal Ctrl-C sends. The script already handles this itself
	// (KeyboardInterrupt around wait_for_session_end(), plus
	// watch_for_game_end's own fallback and end_session_or_die's hard
	// timeout) — this button is just "press Ctrl-C for me".
	state.process.kill('SIGINT');
	appendLog('[sent SIGINT — ending gracefully]');
	return { ok: true };
}

export function forceQuit(): ActionResult {
	if (state.process === null) {
		return { ok: false, error: 'No session is running.' };
	}
	state.process.kill('SIGKILL');
	appendLog('[sent SIGKILL — force quit]');
	return { ok: true };
}

// Best-effort: don't orphan a running kiosk process if the dev server
// itself is stopped without ending the game first.
function killOnExit(): void {
	if (state.process) {
		try {
			state.process.kill('SIGKILL');
		} catch {
			// already gone
		}
	}
}
process.on('exit', killOnExit);
process.on('SIGINT', () => {
	killOnExit();
	process.exit(0);
});
process.on('SIGTERM', () => {
	killOnExit();
	process.exit(0);
});
