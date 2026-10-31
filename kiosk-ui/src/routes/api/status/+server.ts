import { json } from '@sveltejs/kit';
import { getStatus } from '#lib/server/kiosk.ts';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async () => {
	return json(getStatus());
};
