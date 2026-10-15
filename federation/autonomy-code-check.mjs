/** Capability check, not execution: evolving modules must remain pure functions. */
import ts from '../openwiki-upstream/node_modules/typescript/lib/typescript.js';
import {readFile} from 'node:fs/promises';
const file=process.argv[2], testing=process.argv[3]==='test', source=await readFile(file,'utf8');
if(source.length>24000)throw Error('自动升级模块过大');
const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
if(ast.parseDiagnostics.length)throw Error('自动升级模块语法无效');
const forbidden=new Set(['process','globalThis','global','window','self','require','eval','Function','WebAssembly','Reflect','Proxy','constructor','prototype','__proto__','arguments','fetch','Deno','Bun','setTimeout','setInterval','getOwnPropertyDescriptor','getOwnPropertyDescriptors','getOwnPropertyNames','getPrototypeOf','setPrototypeOf','defineProperty','defineProperties','__defineGetter__','__lookupGetter__']);
const declared=new Set(['undefined','NaN','Infinity','Intl','Map','Set','Math','Array','String','Number','Boolean','Object','JSON','URL','RegExp','Error','encodeURI','encodeURIComponent','decodeURI','decodeURIComponent']);
function binding(n){if(!n)return;if(ts.isIdentifier(n))declared.add(n.text);else if(ts.isBindingElement(n))binding(n.name);else if(n.elements)for(const x of n.elements)binding(x);}
function collect(n){
 if(ts.isVariableDeclaration(n)||ts.isParameter(n)||ts.isBindingElement(n)||ts.isFunctionDeclaration(n)||ts.isFunctionExpression(n))binding(n.name);
 if(testing&&(ts.isImportClause(n)||ts.isImportSpecifier(n)))binding(n.name);
 ts.forEachChild(n,collect);
}
collect(ast);
function check(n){
 if(ts.isImportDeclaration(n)){
   if(!testing||!['node:assert/strict','../federation/retrieval.mjs','../federation/learning-strategy.mjs','../federation/tool-strategy.mjs'].includes(n.moduleSpecifier.text))throw Error('不允许的导入');
 }
 if(ts.isImportEqualsDeclaration(n)||ts.isExportDeclaration(n)||ts.isClassDeclaration(n)||ts.isClassExpression(n)
   ||n.kind===ts.SyntaxKind.ThisKeyword||n.kind===ts.SyntaxKind.SuperKeyword||n.kind===ts.SyntaxKind.ImportKeyword)
   throw Error('自动升级只支持纯函数，不允许导入、类或宿主能力');
 if(ts.isElementAccessExpression(n)&&!ts.isNumericLiteral(n.argumentExpression))throw Error('自动升级不允许动态属性访问');
 if(ts.isIdentifier(n)){
   if(forbidden.has(n.text))throw Error('自动升级引用了受保护能力：'+n.text);
   const p=n.parent;
   const property=(ts.isPropertyAccessExpression(p)&&p.name===n)||(ts.isPropertyAssignment(p)&&p.name===n);
   if(!property&&!declared.has(n.text))throw Error('自动升级引用了未声明能力：'+n.text);
 }
 if(ts.isNewExpression(n)){
   const name=n.expression.getText(ast);
   if(!['Intl.Segmenter','Map','Set','URL','RegExp','Error'].includes(name))throw Error('不允许的构造器');
 }
 ts.forEachChild(n,check);
}
check(ast);
process.stdout.write('Pure module capability check passed.\n');
