// Dependency-free mocked-host tests. Run: node .claude/workflows/tests/agent-team.test.mjs
export async function runTests(source) {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const executable = source.replace(/export const meta\s*=/, 'const meta =');
  let passed = 0;
  async function scenario(name, args, reply, check) {
    const calls = [];
    const logs = [];
    const agent = async (prompt, options) => {
      calls.push({prompt, ...options});
      return reply(options.agentType, calls, prompt);
    };
    const result = await new AsyncFunction('args', 'agent', 'log', executable)(args, agent, x => logs.push(x));
    if (!check(result, calls, logs)) throw new Error(name + ': unexpected result or downstream calls');
    passed++;
  }
  const approve = {verdict:'approve', findings:[]};
  const pass = {verdict:'pass', evidence:'mock only: fixture check exited 0', issues:[]};
  const base = {requirement:'Update fixture', scope:['fixture.txt'], acceptance:['fixture matches requested content']};
  const defaults = role => role === 'red-team' ? approve : role === 'verifier' ? pass : 'artifact: fixture.txt';
  await scenario('empty review cannot approve', base,
    role => role === 'red-team' ? null : defaults(role),
    (r,c) => !r.done && !c.some(x => x.agentType === 'developer'));
  await scenario('rejected design cannot reach implementation', base,
    role => role === 'red-team' ? {verdict:'needs_fix',findings:[{severity:'P1',issue:'bad design',trigger:'fixture',suggestion:'revise'}]} : defaults(role),
    (r,c) => !r.done && !c.some(x => x.agentType === 'developer'));
  await scenario('empty verification cannot pass', base,
    role => role === 'verifier' ? null : defaults(role), r => !r.done);
  await scenario('blank evidence cannot pass', base,
    role => role === 'verifier' ? {...pass,evidence:' '} : defaults(role), r => !r.done);
  await scenario('contradictory review cannot approve', base,
    role => role === 'red-team' ? {verdict:'approve',findings:[{severity:'P1',issue:'blocking defect'}]} : defaults(role),
    (r,c) => !r.done && !c.some(x => x.agentType === 'developer'));
  await scenario('success consumes original requirements', base, defaults,
    (r,c) => r.done && c.every(x => x.prompt.includes(base.requirement)));
  await scenario('failed verification returns feedback', base,
    (role,c) => role === 'verifier' && c.filter(x => x.agentType === 'verifier').length === 1
      ? {verdict:'fail',evidence:'mock: mismatch',issues:['FIXTURE_MISMATCH']} : defaults(role),
    (r,c) => r.done && c.filter(x => x.agentType === 'developer')[1]?.prompt.includes('FIXTURE_MISMATCH'));
  await scenario('missing requirement does not dispatch', {}, defaults,
    (r,c) => !r.done && c.length === 0);
  return {passed, note:'Mocked orchestration only; no real agent or gem5 execution'};
}

if (typeof process !== 'undefined' && process.argv?.[1]?.endsWith('agent-team.test.mjs')) {
  const {readFile} = await import('node:fs/promises');
  const source = await readFile(new URL('../agent-team.js', import.meta.url), 'utf8');
  console.log(JSON.stringify(await runTests(source), null, 2));
}
