'use client'
import type {HistoryItem} from '@/features/history/lib/mock'
import {HistoryDetails} from '@/features/history/ui/history-details'
import {Badge} from '@/shared/ui/badge'
import {Button} from '@/shared/ui/button'
import {
    Card,
    CardAction,
    CardContent,
    CardHeader,
    CardTitle,
} from '@/shared/ui/card'
import {Modal} from '@/shared/ui/modal'
import {ArrowUpRight, CalendarDays} from 'lucide-react'
import * as React from 'react'
import {notEmpty} from "@/shared/lib/notEmpty";

export function HistoryCard({item, hideChild = false}: { item: HistoryItem, hideChild?: boolean }) {
    const [open, setOpen] = React.useState(false)
    const genderBadge =
        item.gender === 'male'
            ? {
                label: `Мальчик · ${item.score}`,
                className: 'bg-sky-500/20 text-sky-400 border-sky-500/20',
            }
            : {
                label: `Девочка · ${item.score}`,
                className: 'bg-fuchsia-500/20 text-fuchsia-400 border-fuchsia-500/20',
            }

    return (
        <Card className="border-input">
            <CardHeader className="pt-4 grid grid-cols-[1fr_auto] gap-2">
                <div className="flex items-center gap-2 text-xl text-muted-foreground">
                    <CalendarDays className="size-5"/>
                    <span className="tabular-nums">
            {item.date} {item.time}
          </span>
                </div>
                <CardAction>
                    <Button
                        size="icon"
                        variant="outline"
                        aria-label="Open"
                        className="rounded-xl"
                        onClick={() => setOpen(true)}
                    >
                        <ArrowUpRight className="size-4"/>
                    </Button>
                </CardAction>
                {!hideChild && <div className="col-span-2">
                    <Badge
                        className={`h-9 rounded-full px-4 text-md ${genderBadge.className}`}
                    >
                        {genderBadge.label}
                    </Badge>
                </div>}
            </CardHeader>
            <CardContent
                className="space-y-3 cursor-pointer"
                onClick={() => setOpen(true)}
            >
                <CardTitle className="text-4xl md:text-5xl font-semibold leading-tight">
                    {item.firstName}
                    <br/>
                    {item.lastName}
                </CardTitle>
                <div className="text-muted-foreground text-lg md:text-xl">
                    Врач – {item.doctor}
                </div>
                {notEmpty(item.medsister) && <div className="text-muted-foreground text-lg md:text-xl">
                    Медсестра – {item.medsister}
                </div>}
            </CardContent>
            <Modal open={open} onOpenChange={setOpen}>
                <HistoryDetails onClose={() => setOpen(false)}/>
            </Modal>
        </Card>
    )
}
