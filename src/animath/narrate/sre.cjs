const {mathjax} = require('mathjax-full/js/mathjax.js');
const {TeX} = require('mathjax-full/js/input/tex.js');
const {AllPackages} = require('mathjax-full/js/input/tex/AllPackages.js');
const {liteAdaptor} = require('mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require('mathjax-full/js/handlers/html.js');
const {SerializedMmlVisitor} = require('mathjax-full/js/core/MmlTree/SerializedMmlVisitor.js');
const sre = require('speech-rule-engine');

RegisterHTMLHandler(liteAdaptor());
const tex = new TeX({
  packages: AllPackages.filter((p) => p !== 'bussproofs'),
  formatError: (_, err) => { throw err; },
});
const doc = mathjax.document('', {InputJax: tex});
const mml = new SerializedMmlVisitor();

let input = '';
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', async () => {
  const req = JSON.parse(input);
  await sre.setupEngine({domain: req.domain, modality: 'speech', locale: 'en'});
  await sre.engineReady();
  const out = req.latex.map((t) => {
    try {
      return sre.toSpeech(mml.visitTree(doc.convert(t, {display: false})));
    } catch (e) {
      process.stderr.write(`${JSON.stringify(t)}: ${e.message}\n`);
      process.exit(1);
    }
  });
  process.stdout.write(JSON.stringify(out));
});
