/** Compose the observatory with existing same-origin controls assets. */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFile, writeFile, rename, rm } from 'node:fs/promises';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const web = path.join(root, 'federation/web');
const dependencyRoot = path.join(root, 'openwiki-tools');
const require = createRequire(path.join(dependencyRoot, 'package.json'));
const { build } = require('esbuild');
const checkOnly = process.argv.includes('--check');
if (process.argv.slice(2).some(argument => argument !== '--check')) {
  throw new Error('Usage: node federation/build-observatory.mjs [--check]');
}

// Read every source and finish bundling before replacing either served asset.
// Core/base remain the editable sources for the pre-existing controls.
const [core, base, observatoryCSSSource, heroImage] = await Promise.all([
  readFile(path.join(web, 'federation-controls-core.js'), 'utf8'),
  readFile(path.join(web, 'federation-controls-base.css'), 'utf8'),
  readFile(path.join(web, 'observatory.css'), 'utf8'),
  readFile(path.join(web, 'assets/observatory-astrolabe-v2.jpg')),
]);
const observatoryCSS = observatoryCSSSource.replaceAll(
  '__OBSERVATORY_HERO_IMAGE__',
  `data:image/jpeg;base64,${heroImage.toString('base64')}`,
);
const bundled = await build({
  absWorkingDir: root,
  entryPoints: [path.join(web, 'observatory.js')],
  outfile: path.join(web, 'observatory-bundle.js'),
  nodePaths: [path.join(dependencyRoot, 'node_modules')],
  bundle: true,
  write: false,
  minify: false,
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  charset: 'utf8',
  legalComments: 'inline',
  logLevel: 'warning',
});
if (bundled.outputFiles.length !== 1) {
  throw new Error('Observatory build must produce one self-contained JavaScript file.');
}

const outputs = [
  ['federation-controls.js', `${core}\n;\n/* Generated observatory: edit observatory.js / observatory-model.js, then rebuild. */\n${bundled.outputFiles[0].text}`],
  ['federation-controls.css', `${base}\n/* Generated observatory: edit observatory.css, then rebuild. */\n${observatoryCSS}`],
];
if (checkOnly) {
  for (const [name, content] of outputs) {
    if (await readFile(path.join(web, name), 'utf8') !== content) {
      throw new Error(`${name} is outdated. Run node federation/build-observatory.mjs.`);
    }
  }
  process.stdout.write('Observatory assets match their sources.\n');
} else {
  const staged = outputs.map(([name, content]) => ({
    name,
    content,
    target: path.join(web, name),
    temporary: path.join(web, `.${name}.observatory-${process.pid}.tmp`),
  }));
  try {
    for (const output of staged) await writeFile(output.temporary, output.content, { flag: 'wx' });
    for (const output of staged) await rename(output.temporary, output.target);
  } finally {
    for (const output of staged) await rm(output.temporary, { force: true });
  }
  process.stdout.write('Built federation-controls.js and federation-controls.css with the observatory.\n');
}
