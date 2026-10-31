<script lang="ts">
	type Status = {
		running: boolean;
		difficulty: number | null;
		startedAt: number | null;
		log: string[];
	};

	const DIFFICULTY_LABELS: Record<number, string> = {
		1: 'Easiest',
		2: 'Easy',
		3: 'Easy',
		4: 'Medium-easy',
		5: 'Medium',
		6: 'Medium',
		7: 'Medium-hard',
		8: 'Hard',
		9: 'Hard',
		10: 'Hardest'
	};

	let selectedDifficulty = $state(5);
	let running = $state(false);
	let activeDifficulty = $state<number | null>(null);
	let startedAt = $state<number | null>(null);
	let log = $state<string[]>([]);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let logEl: HTMLPreElement | undefined = $state();
	let now = $state(Date.now());

	async function poll(): Promise<void> {
		try {
			const res = await fetch('/api/status');
			const data: Status = await res.json();
			running = data.running;
			activeDifficulty = data.difficulty;
			startedAt = data.startedAt;
			log = data.log;
		} catch {
			// dev server hiccup — next tick will retry
		}
	}

	$effect(() => {
		poll();
		const pollId = setInterval(poll, 1000);
		const clockId = setInterval(() => (now = Date.now()), 1000);
		return () => {
			clearInterval(pollId);
			clearInterval(clockId);
		};
	});

	$effect(() => {
		log; // re-run whenever the log changes
		if (logEl) logEl.scrollTop = logEl.scrollHeight;
	});

	const elapsedLabel = $derived.by(() => {
		if (!running || startedAt === null) return null;
		const secs = Math.max(0, Math.floor((now - startedAt) / 1000));
		const m = Math.floor(secs / 60);
		const s = secs % 60;
		return `${m}:${s.toString().padStart(2, '0')}`;
	});

	async function post(path: string, body?: unknown): Promise<void> {
		busy = true;
		error = null;
		try {
			const res = await fetch(path, {
				method: 'POST',
				headers: body ? { 'content-type': 'application/json' } : undefined,
				body: body ? JSON.stringify(body) : undefined
			});
			const data = await res.json();
			if (!data.ok) error = data.error;
			await poll();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			busy = false;
		}
	}

	const start = () => post('/api/start', { difficulty: selectedDifficulty });
	const endGracefully = () => post('/api/end');
	const forceQuit = () => post('/api/kill');
</script>

<main class="mx-auto flex h-screen max-w-3xl flex-col gap-6 overflow-hidden bg-slate-950 p-6 text-slate-100">
	<header>
		<h1 class="text-3xl font-bold text-orange-400">🏴‍☠️ Captain Barnaby Bones</h1>
		<p class="mt-1 text-sm text-slate-400">
			Drives <code class="text-slate-300">pirate_riddle_kiosk.py</code> — one kid's session at a
			time.
		</p>
	</header>

	<section class="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 p-5">
		<span class="h-3 w-3 shrink-0 rounded-full {running ? 'animate-pulse bg-green-500' : 'bg-slate-600'}"
		></span>
		{#if running}
			<p class="font-semibold">
				Session running — difficulty {activeDifficulty} ({DIFFICULTY_LABELS[activeDifficulty ?? 0] ??
					'?'}) — {elapsedLabel}
			</p>
		{:else}
			<p class="text-slate-400">Idle — pick a difficulty and start a session.</p>
		{/if}
	</section>

	<section class="rounded-lg border border-slate-800 bg-slate-900 p-5">
		<p class="mb-3 text-sm font-medium text-slate-300">
			Riddle difficulty — {selectedDifficulty} ({DIFFICULTY_LABELS[selectedDifficulty]})
		</p>
		<div class="grid grid-cols-10 gap-2">
			{#each Array.from({ length: 10 }, (_, i) => i + 1) as n (n)}
				<button
					type="button"
					disabled={running || busy}
					onclick={() => (selectedDifficulty = n)}
					class="rounded-md py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40
						{selectedDifficulty === n
						? 'bg-orange-500 text-slate-950'
						: 'bg-slate-800 text-slate-200 hover:bg-slate-700'}"
				>
					{n}
				</button>
			{/each}
		</div>
	</section>

	<section class="grid grid-cols-3 gap-4">
		<button
			type="button"
			disabled={running || busy}
			onclick={start}
			class="rounded-lg bg-green-600 py-4 text-lg font-bold text-white transition-colors hover:bg-green-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
		>
			Start
		</button>
		<button
			type="button"
			disabled={!running || busy}
			onclick={endGracefully}
			class="rounded-lg bg-amber-600 py-4 text-lg font-bold text-white transition-colors hover:bg-amber-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
		>
			End Gracefully
		</button>
		<button
			type="button"
			disabled={!running || busy}
			onclick={forceQuit}
			class="rounded-lg bg-red-700 py-4 text-lg font-bold text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
		>
			Force Quit
		</button>
	</section>

	{#if error}
		<p class="rounded-md border border-red-800 bg-red-950 px-4 py-2 text-sm text-red-300">
			{error}
		</p>
	{/if}

	<section class="flex min-h-0 flex-1 flex-col rounded-lg border border-slate-800 bg-slate-900">
		<p class="border-b border-slate-800 px-4 py-2 text-xs font-medium tracking-wide text-slate-400 uppercase">
			Session log
		</p>
		<pre
			bind:this={logEl}
			class="min-h-0 flex-1 overflow-y-auto p-4 text-xs leading-relaxed whitespace-pre-wrap text-slate-300"
		>{log.length ? log.join('\n') : '(nothing yet)'}</pre>
	</section>
</main>
