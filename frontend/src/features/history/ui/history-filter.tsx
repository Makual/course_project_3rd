'use client'

import { Button } from '@/shared/ui/button'
import { Calendar } from '@/shared/ui/calendar'
import { Input } from '@/shared/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/ui/popover'
import { format } from 'date-fns'
import { CalendarDays, Search } from 'lucide-react'
import * as React from 'react'

export function HistoryFilter() {
  const [date, setDate] = React.useState<Date | undefined>(undefined)

  return (
    <div className="sticky bottom-0 left-0 right-0 z-20 mt-6">
      <div className="rounded-xl bg-background/70 backdrop-blur border border-input p-3 flex items-center gap-2 flex-wrap">
        <div className="flex gap-2">
          <Button variant="secondary">Все</Button>
          <Button variant="outline">Сегодня</Button>
          <Button variant="outline">Вчера</Button>
          <Button variant="outline">Прошлая неделя</Button>

          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="gap-2">
                <CalendarDays className="size-4" />
                {date ? format(date, 'dd.MM.yyyy') : 'Выбрать дату'}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-2" align="start">
              <Calendar
                mode="single"
                selected={date}
                onSelect={setDate}
                showOutsideDays
                initialFocus
              />
            </PopoverContent>
          </Popover>
        </div>
        <div className="ml-auto flex items-center gap-2 min-w-[260px]">
          <Search className="size-4 text-muted-foreground" />
          <Input placeholder="ФИО или СНИЛС" className="w-[260px]" />
        </div>
      </div>
    </div>
  )
}
