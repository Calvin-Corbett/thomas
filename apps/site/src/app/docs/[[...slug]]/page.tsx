import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocsPage } from "@/components/docs-page";
import { getDocPage, getDocStaticParams } from "@/lib/docs";
import { buildDocMetadata } from "@/lib/site-metadata";

export function generateStaticParams() {
  return getDocStaticParams();
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = getDocPage("en", slug);

  if (!page) {
    return {};
  }

  return buildDocMetadata("en", page);
}

export default async function DocsIndexPage({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}) {
  const { slug } = await params;
  const page = getDocPage("en", slug);

  if (!page) {
    notFound();
  }

  return <DocsPage locale="en" page={page} />;
}
