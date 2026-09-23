import { PlusIcon } from '@heroicons/react/16/solid'
import { ChatBubbleLeftRightIcon, ShieldCheckIcon } from '@heroicons/react/20/solid'
import {
  Sidebar,
  SidebarBody,
  SidebarFooter,
  SidebarHeader,
  SidebarHeading,
  SidebarItem,
  SidebarLabel,
  SidebarSection,
} from '../components/sidebar'
import { formatGameDate } from './GameHeader'
import { team } from './teams'

export function BrandMark({ className = 'size-7' }) {
  return (
    <span className={`${className} grid shrink-0 place-items-center rounded-lg bg-zinc-950 dark:bg-white`}>
      <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" className="size-[65%] stroke-white dark:stroke-zinc-950">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3v18M5.6 5.6c3 3 3 9.8 0 12.8M18.4 5.6c-3 3-3 9.8 0 12.8" />
      </svg>
    </span>
  )
}

function TeamLine({ abbr, score, won }) {
  return (
    <>
      <span className={`flex items-center gap-2 ${won ? 'font-semibold' : 'font-normal text-zinc-500 dark:text-zinc-400'}`}>
        <span className="size-2 rounded-[3px]" style={{ background: team(abbr).color }} />
        {abbr}
      </span>
      <span className={`text-right font-score text-[17px]/5 tabular-nums ${won ? 'font-semibold' : 'font-medium text-zinc-500 dark:text-zinc-400'}`}>
        {score}
      </span>
    </>
  )
}

function Placeholder({ children }) {
  return <p className="px-2 py-1 text-sm/6 text-zinc-500 dark:text-zinc-400">{children}</p>
}

export function AppSidebar({ view, games, conversations, currentGameId, currentConversationId, onView, onNewQuestion, onSelectGame, onSelectConversation }) {
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="mb-3 flex items-center gap-3 px-2">
          <BrandMark />
          <div className="min-w-0">
            <div className="text-sm/5 font-semibold text-zinc-950 dark:text-white">Postgame Desk</div>
            <div className="text-xs/4 text-zinc-500 dark:text-zinc-400">Fact-checked game breakdowns</div>
          </div>
        </div>
        <SidebarSection>
          <SidebarItem onClick={onNewQuestion}>
            <PlusIcon />
            <SidebarLabel>New question</SidebarLabel>
          </SidebarItem>
        </SidebarSection>
      </SidebarHeader>

      <SidebarBody>
        <SidebarSection>
          <SidebarHeading>Recent finals</SidebarHeading>
          {games.status === 'loading' && <Placeholder>Loading games…</Placeholder>}
          {games.status === 'error' && <Placeholder>Couldn't load recent games.</Placeholder>}
          {games.status === 'ok' && games.items.length === 0 && <Placeholder>No recent finals found.</Placeholder>}
          {games.items.map((g) => {
            let awayWon = g.away_score > g.home_score
            return (
              <SidebarItem key={g.game_id} current={view === 'ask' && g.game_id === currentGameId} onClick={() => onSelectGame(g)}>
                <span className="grid w-full grid-cols-[1fr_auto] gap-x-3 gap-y-0.5">
                  <TeamLine abbr={g.away_team_abbr} score={g.away_score} won={awayWon} />
                  <TeamLine abbr={g.home_team_abbr} score={g.home_score} won={!awayWon} />
                  <span className="col-span-2 pt-0.5 text-xs/4 font-normal text-zinc-500 dark:text-zinc-400">
                    {[g.season_type === 'Playoffs' ? 'Playoffs' : null, formatGameDate(g.game_date)].filter(Boolean).join(' · ')}
                  </span>
                </span>
              </SidebarItem>
            )
          })}
        </SidebarSection>

        <SidebarSection>
          <SidebarHeading>Your conversations</SidebarHeading>
          {conversations.status === 'ok' && conversations.items.length === 0 && <Placeholder>Questions you ask show up here.</Placeholder>}
          {conversations.status === 'error' && <Placeholder>Couldn't load conversations.</Placeholder>}
          {conversations.items.map((c) => (
            <SidebarItem
              key={c.conversation_id}
              current={view === 'ask' && c.conversation_id === currentConversationId}
              onClick={() => onSelectConversation(c.conversation_id)}
            >
              <span className="min-w-0">
                <SidebarLabel className="block">{c.question}</SidebarLabel>
                <span className="block truncate text-xs/4 font-normal text-zinc-500 dark:text-zinc-400">
                  {[c.game_label, c.runs > 1 ? `${c.runs} questions` : null].filter(Boolean).join(' · ')}
                </span>
              </span>
            </SidebarItem>
          ))}
        </SidebarSection>
      </SidebarBody>

      <SidebarFooter>
        <SidebarSection>
          <SidebarItem current={view === 'ask'} onClick={() => onView('ask')}>
            <ChatBubbleLeftRightIcon />
            <SidebarLabel>Ask about a game</SidebarLabel>
          </SidebarItem>
          <SidebarItem current={view === 'reliability'} onClick={() => onView('reliability')}>
            <ShieldCheckIcon />
            <SidebarLabel>How reliable is this?</SidebarLabel>
          </SidebarItem>
        </SidebarSection>
      </SidebarFooter>
    </Sidebar>
  )
}
