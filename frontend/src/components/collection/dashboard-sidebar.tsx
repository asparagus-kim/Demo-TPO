import { HugeiconsIcon } from "@hugeicons/react"
import { Analytics01Icon } from "@hugeicons/core-free-icons"
import { Link } from "react-router-dom"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { BrandWordmark } from "@/components/yielda/brand"
import { NAV, type Section } from "./dashboard-nav"

export function DashboardSidebar({
  section,
  onSectionChange,
  recordCount,
}: {
  section: Section
  onSectionChange: (next: Section) => void
  recordCount: number
}) {
  return (
    <Sidebar collapsible="icon">
      {/* 페이지 헤더의 브랜드는 워드마크만 쓴다 (top-nav·온보딩과 동일).
          BrandMark 는 콘텐츠 내부 히어로 전용. 아이콘 모드로 접히면 로고 자리는
          비운다 — 접기 토글은 헤더의 SidebarTrigger 가 계속 담당한다. */}
      <SidebarHeader className="group-data-[collapsible=icon]:hidden">
        {/* BrandWordmark 자체가 클릭 시 "/" 로 이동한다 — Link 로 또 감싸지 않는다. */}
        <div className="flex cursor-pointer flex-col gap-0.5 px-3 py-1 leading-none">
          <BrandWordmark />
          <span className="text-xs text-muted-foreground">분석 수집</span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>대시보드</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton
                    isActive={section === item.id}
                    tooltip={item.label}
                    onClick={() => onSectionChange(item.id)}
                  >
                    <HugeiconsIcon icon={item.icon} />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                  {item.id === "records" ? (
                    <SidebarMenuBadge>{recordCount}</SidebarMenuBadge>
                  ) : null}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="분석 시작" asChild>
              <Link to="/">
                <HugeiconsIcon icon={Analytics01Icon} />
                <span>분석 화면으로</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
