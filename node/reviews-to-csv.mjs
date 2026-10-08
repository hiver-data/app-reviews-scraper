// Google Play and App Store reviews to one CSV, via the hiver/app-reviews-scraper Actor on Apify.
//
//   npm install
//   export APIFY_TOKEN=...   # Apify Console > Settings > API & Integrations
//   node reviews-to-csv.mjs com.spotify.music 324684580 --ratings 1,2 --since 2026-10-01
//
// Apps can be Google Play package names or URLs and App Store IDs or URLs, mixed in one list.
import { writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { ApifyClient } from 'apify-client';

const ACTOR = 'hiver/app-reviews-scraper';
const COLUMNS = ['store', 'appId', 'appName', 'country', 'rating', 'title', 'text', 'date', 'appVersion',
    'thumbsUp', 'isEdited', 'developerReply', 'developerReplyDate', 'reviewUrl', 'reviewId', 'error'];

const { values: opt, positionals: apps } = parseArgs({
    allowPositionals: true,
    options: {
        countries: { type: 'string', default: 'us' }, // comma-separated, e.g. us,gb,de
        ratings: { type: 'string' }, // comma-separated, e.g. 1,2
        since: { type: 'string' }, // YYYY-MM-DD
        max: { type: 'string', default: '100' }, // reviews per app and country, 1-5000
        'max-charge': { type: 'string', default: '1.00' }, // stop the run once it has cost this many USD
        out: { type: 'string', default: 'reviews.csv' },
    },
});
if (!apps.length) throw new Error('Give at least one app: com.spotify.music, 324684580 or a store URL.');
if (!process.env.APIFY_TOKEN) throw new Error('Set APIFY_TOKEN (Apify Console > Settings > API & Integrations).');

const input = {
    apps,
    countries: opt.countries.split(','),
    maxReviewsPerApp: Number(opt.max),
    sort: 'newest',
    ...(opt.ratings && { ratings: opt.ratings.split(',') }),
    ...(opt.since && { sinceDate: opt.since }),
};

// APIFY_API_BASE_URL is only for testing against a mock server; leave it unset.
const client = new ApifyClient({ token: process.env.APIFY_TOKEN, baseUrl: process.env.APIFY_API_BASE_URL });
const run = await client.actor(ACTOR).call(input, { maxTotalChargeUsd: Number(opt['max-charge']) });
if (run.status !== 'SUCCEEDED') throw new Error(`Run did not succeed: ${run.status} ${run.statusMessage ?? ''}`);

const { items } = await client.dataset(run.defaultDatasetId).listItems();
const cell = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const lines = [COLUMNS.join(','), ...items.map((r) => COLUMNS.map((c) => cell(r[c])).join(','))];
writeFileSync(opt.out, `${lines.join('\r\n')}\r\n`);
console.log(`${items.length} rows (${items.filter((r) => r.error).length} error rows) -> ${opt.out}`);
console.log(`Run ${run.id}: ${run.statusMessage}`);
