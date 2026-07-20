import { auth } from "@/lib/auth"
import ChatWindow from "@/components/chat/ChatWindow"

export default async function ChatPage() {
  const session = await auth()
  const token = (session as any)?.backendToken || ""
  return <ChatWindow token={token} />
}
