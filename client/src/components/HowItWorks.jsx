import { useSite } from '../context/SiteContext.jsx';

export default function HowItWorks() {
  const { settings } = useSite();
  if (settings.howto_enabled !== 'true') return null;

  const steps = [
    { n: 1, title: settings.howto_step1_title, desc: settings.howto_step1_desc },
    { n: 2, title: settings.howto_step2_title, desc: settings.howto_step2_desc },
    { n: 3, title: settings.howto_step3_title, desc: settings.howto_step3_desc },
  ];

  return (
    <section className="mb-10">
      <h2 className="text-xl font-bold mb-4">Comment ça marche ?</h2>
      <div className="grid sm:grid-cols-3 gap-4">
        {steps.map((s) => (
          <div key={s.n} className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
            <div className="w-9 h-9 rounded-full border border-zinc-700 flex items-center justify-center font-bold mb-3">
              {s.n}
            </div>
            <h3 className="font-semibold mb-1">{s.title}</h3>
            <p className="text-sm text-sub leading-relaxed">{s.desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
