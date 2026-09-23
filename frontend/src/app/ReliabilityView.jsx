import { Badge } from '../components/badge'
import { Heading } from '../components/heading'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/table'
import { Text } from '../components/text'

// Placeholder figures until the evaluation runs; the page labels them as samples.
const evaluation = {
  highlights: [
    { label: 'Claims backed by data', value: '94%', note: 'vs 71% with no fact-check' },
    { label: 'Said "not sure" when it should', value: '9 of 10', note: "Questions the data couldn't answer" },
    { label: 'Typical wait', value: '34 s', note: 'About 3× longer than no fact-check' },
  ],
  configurations: [
    { name: 'Basic', description: 'Looks up data, answers once', accurate: 74, supported: 71, refusals: '4 / 10', seconds: 11, cost: '$0.012' },
    { name: '+ Fact-check', description: 'Checks every claim, rewrites weak ones', accurate: 86, supported: 91, refusals: '8 / 10', seconds: 24, cost: '$0.021' },
    { name: '+ Fact-check & follow-up lookups', description: 'Fetches more data when a claim is thin', accurate: 90, supported: 94, refusals: '9 / 10', seconds: 34, cost: '$0.029', current: true },
  ],
}

export function ReliabilityView() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-4 py-8 sm:px-6 lg:py-10">
      <div>
        <p className="text-xs/5 font-semibold tracking-wider text-zinc-500 uppercase dark:text-zinc-400">Evaluation</p>
        <Heading className="mt-1">How reliable are the answers?</Heading>
        <Text className="mt-2 max-w-[62ch]">
          Every answer is checked claim by claim against the game data before you see it. To test whether that checking
          actually helps, the same 30 questions from 10 games were run through three versions of the analyst.
        </Text>
        <Badge color="amber" className="mt-3">
          Sample figures · evaluation not yet run
        </Badge>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {evaluation.highlights.map((h) => (
          <div key={h.label} className="rounded-xl p-4 ring-1 ring-zinc-950/10 dark:ring-white/10">
            <div className="text-sm/6 text-zinc-500 dark:text-zinc-400">{h.label}</div>
            <div className="mt-1 font-score text-3xl/9 font-semibold text-zinc-950 tabular-nums dark:text-white">{h.value}</div>
            <div className="text-[13px]/5 text-zinc-500 dark:text-zinc-400">{h.note}</div>
          </div>
        ))}
      </div>

      <Table className="[--gutter:--spacing(4)] sm:[--gutter:--spacing(6)]">
        <TableHead>
          <TableRow>
            <TableHeader>Version</TableHeader>
            <TableHeader className="text-right">Accurate</TableHeader>
            <TableHeader className="text-right">Claims backed</TableHeader>
            <TableHeader className="text-right">Right to refuse</TableHeader>
            <TableHeader className="text-right">Avg time</TableHeader>
            <TableHeader className="text-right">Avg cost</TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {evaluation.configurations.map((c) => (
            <TableRow key={c.name}>
              <TableCell>
                <div className="flex items-center gap-2 font-medium text-zinc-950 dark:text-white">
                  {c.name}
                  {c.current && <Badge color="green">What you use</Badge>}
                </div>
                <div className="text-zinc-500 dark:text-zinc-400">{c.description}</div>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                <span className="mr-2 inline-block h-1.5 rounded-full bg-zinc-400 align-middle dark:bg-zinc-500" style={{ width: c.accurate * 0.6 }} />
                {c.accurate}%
              </TableCell>
              <TableCell className="text-right tabular-nums">{c.supported}%</TableCell>
              <TableCell className="text-right tabular-nums">{c.refusals}</TableCell>
              <TableCell className="text-right tabular-nums">{c.seconds} s</TableCell>
              <TableCell className="text-right tabular-nums">{c.cost}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Text>
        These results describe this app on this question set, not AI analysis in general. In the full build each row
        opens examples of where that version got things wrong.
      </Text>
    </div>
  )
}
