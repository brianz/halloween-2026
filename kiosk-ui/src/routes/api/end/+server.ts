import { json } from '@sveltejs/kit';
import { endGracefully } from '#lib/server/kiosk.ts';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async () => {
	const result = endGracefully();
	return json(result, { status: result.ok ? 200 : 409 });
};
