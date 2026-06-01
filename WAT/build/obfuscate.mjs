// WAT 난독화 빌드: src/ 의 읽기 가능한 원본을 읽어, inline <script> 블록만
// 난독화하여 서빙 파일(WAT/index.html, WAT/irs/index.html)로 출력한다.
// 외부 CDN <script src=...> 태그는 건드리지 않는다 (SRI 유지).
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import JavaScriptObfuscator from 'javascript-obfuscator';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');

// [읽기용 원본, 난독화 출력(서빙)]
const TARGETS = [
  { src: resolve(root, 'src/index.html'),            out: resolve(root, 'index.html') },
  { src: resolve(root, 'src/irs/index.html'),        out: resolve(root, 'irs/index.html') },
  { src: resolve(root, 'src/accounting/index.html'), out: resolve(root, 'accounting/index.html') },
];

// renameGlobals:false → HTML onclick="fn()" 등에서 부르는 전역 함수명 보존 (깨짐 방지)
const OPTS = {
  compact: true,
  controlFlowFlattening: false,   // 켜면 무겁고 가끔 깨짐
  deadCodeInjection: false,
  renameGlobals: false,           // 핵심: 전역 함수/변수명 유지
  identifierNamesGenerator: 'mangled',
  stringArray: true,
  stringArrayEncoding: ['base64'],
  stringArrayThreshold: 0.75,
  selfDefending: false,
  disableConsoleOutput: false,
  numbersToExpressions: true,
  simplify: true,
};

// 속성 없는 <script>...</script> 만 매칭 (CDN <script src=...> 제외)
const INLINE_RE = /<script>([\s\S]*?)<\/script>/g;

function syntaxOk(code) {
  try { new Function(code); return true; }
  catch (e) { return e.message; }
}

let failed = false;
for (const { src, out } of TARGETS) {
  let html = readFileSync(src, 'utf8');
  let n = 0, errors = [];
  html = html.replace(INLINE_RE, (m, body) => {
    if (!body.trim()) return m;
    const res = JavaScriptObfuscator.obfuscate(body, OPTS).getObfuscatedCode();
    const chk = syntaxOk(res);
    if (chk !== true) { errors.push(chk); return m; }  // 깨지면 원본 유지
    n++;
    return `<script>${res}</script>`;
  });
  if (errors.length) { console.error(`[FAIL] ${src}: ${errors.length} block(s) syntax error: ${errors[0]}`); failed = true; continue; }
  writeFileSync(out, html, 'utf8');
  console.log(`[OK] ${src} -> ${out}  (inline scripts obfuscated: ${n})`);
}
process.exit(failed ? 1 : 0);
