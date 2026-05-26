'use client'

import {type CtgPoint, type CtgStatus, getStatusBadge, getStatusColors,} from '@/features/ctg/lib/mock'
import {cn} from '@/shared/lib/css'
import {Badge} from '@/shared/ui/badge'
import {Button} from '@/shared/ui/button'
import {Card, CardAction, CardContent, CardHeader} from '@/shared/ui/card'
import {ChartContainer} from '@/shared/ui/chart'
import {Flex} from '@/shared/ui/flex'
import {AlertTriangle, Archive, ArrowUpRight, HeartPulse, Smile} from 'lucide-react'
import * as React from 'react'
import {D3CTG} from '@/shared/ui/d3-ctg'
import Link from 'next/link'
import {
    useGetMonitorInfoApiMonitorsMonitorIdGet
} from "@/entities/generated/endpoints/ктг-мониторинг-api-v10-0-1-гц";

type Props = {
    title: string
    room: string
    status: CtgStatus
    data: CtgPoint[]
    monitorId?: string
    fhrSegments?: { start: number; end: number; color: string }[]
    fhrEventBands?: { start: number; end: number; color: string }[]
}

export function CtgCard({title, room, status, data, monitorId, fhrSegments = [], fhrEventBands = []}: Props) {
    const colors = getStatusColors(status)
    const badge = getStatusBadge(status)

    const last = data[data.length - 1]
    const fhr = Math.round(last?.heart_beat ?? 0)
    const activity = Math.round(
        data.reduce((acc, p) => acc + Math.max(0, p.pussy_power), 0) / data.length
    )
    const monitorData = useGetMonitorInfoApiMonitorsMonitorIdGet(monitorId || '');

    return (
        <Card
            className={cn(
                'p-0 backdrop-blur bg-background/60 border-input',
            )}
        >
            <CardHeader className="pt-4 grid grid-cols-[1fr_auto] items-center gap-2">
                <div className="flex items-center gap-2">
                    <div className="text-base text-md font-medium">{title}</div>
                    <div className="text-muted-foreground text-md">{room}</div>
                </div>
                <Flex className={'items-center gap-2'}>
                    <div className="col-span-2">
                        {monitorData.data?.is_running && <Badge
                            variant={badge.variant}
                            className={cn(
                                {
                                    normal:
                                        'bg-emerald-600/20 text-emerald-400 border-emerald-500/20',
                                    chronic: 'bg-amber-500/20 text-amber-400 border-amber-500/20',
                                    acute: '',
                                }[status] || '',
                                'h-9 text-md'
                            )}
                        >
                            {
                                {
                                    normal: <Smile className="size-9"/>,
                                    acute: <HeartPulse className="size-9"/>,
                                    chronic: <AlertTriangle className="w-9 h-9"/>,
                                }[status]
                            }
                            Работает
                        </Badge>}
                        {monitorData.data?.is_done && !monitorData.data?.is_running &&
                            <Badge variant={'outline'} className={'h-9 text-md'}><Archive
                                className={'size-9'}/> Завершен</Badge>}
                    </div>
                    <CardAction className="row-start-1 col-start-2">
                        {monitorId ? (
                            <Link href={`/start-process?monitor_id=${monitorId}`}
                                  onClick={() => typeof window !== 'undefined' ? sessionStorage.setItem('ktg_monitor_id', monitorId) : ''}>
                                <Button variant="outline" size="icon" aria-label="Open">
                                    <ArrowUpRight className="size-4"/>
                                </Button>
                            </Link>
                        ) : (
                            <Button variant="outline" size="icon" aria-label="Open">
                                <ArrowUpRight className="size-4"/>
                            </Button>
                        )}
                    </CardAction>
                </Flex>
            </CardHeader>
            <CardContent className="pl-0 relative flex flex-row box-border">
                <ChartContainer
                    className="h-[210px] relative rounded-xl w-full box-border z-10"
                    config={{
                        'heart_beat': {color: colors.heart_beat},
                        'pussy_power': {color: colors.pussy_power},
                    }}
                >
                    <D3CTG name={'ЧСС'} data={data as any}
                           yDomain={[80, 200]} color={colors.heart_beat} valueKey={'heart_beat' as any}
                           lineSegments={fhrSegments as any} eventBands={fhrEventBands as any}
                           thresholdsY={[100,120,160,180]}
                    />
                </ChartContainer>
                <hr
                    className={cn(
                        'border-none z-30 absolute top-0 right-1 w-12 h-[210px] bg-gradient-to-r from-transparent to-background',
                    )}
                />
                <Flex
                    className={cn(
                        'flex-col justify-between pr-1 z-20 pb-4 items-end',
                    )}
                >
                    <div className="font-semibold text-md tracking-wide">ЧСС</div>
                    <div className={cn("text-5xl font-semibold tabular-nums leading-none", !fhr && 'text-2xl')}>
                        {fhr || 'Нет данных'}
                    </div>
                    <div className="text-right mt-6 font-semibold text-md w-[165px]">
                        Сократительная активность матки
                    </div>
                    <div
                        className={cn("text-right text-5xl font-semibold tabular-nums leading-none", !activity && 'text-2xl')}>
                        {activity || 'Нет данных'}
                    </div>
                </Flex>
            </CardContent>
        </Card>
    )
}


