'use client'

import type {CtgPoint} from '@/features/ctg/lib/mock'
import {cn} from '@/shared/lib/css'
import {Badge} from '@/shared/ui/badge'
import {Card, CardContent} from '@/shared/ui/card'
import {ChartContainer} from '@/shared/ui/chart'
import {D3CTG} from '@/shared/ui/d3-ctg'
import * as React from 'react'
import {Area, AreaChart, CartesianGrid, Tooltip, XAxis, YAxis} from 'recharts'

type Props = {
    data: CtgPoint[]
    lineKey: keyof CtgPoint
    color: string
    value: number
    valueTitle: string
    status?: 'normal' | 'chronic' | 'acute'
    className?: string
    areaName?: string
}

export function CtgPanel({
                             data,
                             lineKey,
                             color,
                             value,
                             valueTitle,
                             status = 'normal',
                             areaName,
                             className,
                         }: Props) {
    const badgeClass = {
        normal: 'bg-emerald-600/20 text-emerald-400 border-emerald-500/20',
        chronic: 'bg-amber-500/20 text-amber-400 border-amber-500/20',
        acute: 'bg-red-600/20 text-red-400 border-red-500/20',
    }[status]

    const DataFormater = (number: number) => {
        if(number > 1000000000){
            return (number/1000000000).toString() + 'B';
        }else if(number > 1000000){
            return (number/1000000).toString() + 'M';
        }else if(number > 1000){
            return (number/1000).toString() + 'K';
        }else{
            return (number.toFixed(2)).toString();
        }
    }

    return (
        <Card className={cn('border-input p-0', className)}>
            <CardContent className="p-0 flex">
                <ChartContainer className="h-[230px] rounded-l-xl w-full" config={{ [String(lineKey)]: {color} }}>
                    <D3CTG name={areaName} data={data as any} yDomain={lineKey === 'heart_beat' ? [80,200] : [0,120]} color={color} valueKey={lineKey as any} />
                </ChartContainer>

                <div
                    className="w-44 shrink-0 px-4 py-4 flex flex-col justify-between items-end border-l border-input rounded-r-xl">
                    <Badge className={cn('h-7', badgeClass)}>Норма</Badge>
                    <div className="text-right space-y-2">
                        <div className="text-md font-semibold text-muted-foreground">
                            {valueTitle}
                        </div>
                        <div className="text-6xl font-semibold tabular-nums leading-none">
                            {value}
                        </div>
                    </div>
                </div>
            </CardContent>
        </Card>
    )
}


