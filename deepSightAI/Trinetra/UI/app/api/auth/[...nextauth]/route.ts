import NextAuth from "next-auth";
import { dsai_authOptions } from "@/lib/auth/dsai_authOptions";

const dsai_handler = NextAuth(dsai_authOptions);
export { dsai_handler as GET, dsai_handler as POST };
