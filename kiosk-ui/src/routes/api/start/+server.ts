import { json } from '@sveltejs/kit';
import { startKiosk } from '#lib/server/kiosk.ts';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request }) => {
	const body = await request.json().catch(() => null);
	const difficulty = Number(body?.difficulty);
	const result = startKiosk(difficulty);
	return json(result, { status: result.ok ? 200 : 409 });
};
