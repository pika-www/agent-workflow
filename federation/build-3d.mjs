/** Bundle pinned, locally installed open-source 3D dependencies for same-origin use. */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dependencyRoot = path.join(root, 'openwiki-tools');
const require = createRequire(path.join(dependencyRoot, 'package.json'));
const { build } = require('esbuild');
const vendor = path.join(root, 'federation/web/vendor');
await mkdir(vendor, { recursive: true });
const result = await build({
  entryPoints: [path.join(root, 'federation/web/knowledge-graph-3d.js')],
  outfile: path.join(vendor, 'knowledge-graph-3d.js'),
  nodePaths: [path.join(dependencyRoot, 'node_modules')],
  bundle: true, minify: true, format: 'esm', platform: 'browser', target: 'es2022',
  legalComments: 'external', logLevel: 'info', metafile: true,
});
const notices = [];
const packages = new Set(Object.keys(result.metafile.inputs)
  .map(input => input.match(/node_modules\/((?:@[^/]+\/)?[^/]+)/)?.[1]).filter(Boolean));
for (const name of [...packages].sort()) {
  const packageDir = path.join(dependencyRoot, 'node_modules', name);
  const metadata = JSON.parse(await readFile(path.join(packageDir, 'package.json'), 'utf8'));
  const licenseFile = (await readdir(packageDir)).find(file => /^licen[cs]e(?:\.|$)/i.test(file));
  if (!licenseFile) throw new Error(`Missing bundled dependency license: ${name}`);
  const license = await readFile(path.join(packageDir, licenseFile), 'utf8');
  notices.push(`${name}@${metadata.version} (${metadata.license || 'see license below'})\n${metadata.repository?.url || ''}\n\n${license}`);
}
await writeFile(path.join(vendor, 'THIRD-PARTY-LICENSES.txt'), notices.join('\n\n---\n\n'));
