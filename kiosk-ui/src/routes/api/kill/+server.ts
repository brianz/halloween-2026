import { json } from '@sveltejs/kit';
import { forceQuit } from '#lib/server/kiosk.ts';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async () => {
	const result = forceQuit();
	return json(result, { status: result.ok ? 200 : 409 });
};
