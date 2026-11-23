import { notFound, redirect } from "next/navigation";

const SHORT_CODE_RE = /^[0-9a-z]{15}$/;

/**
 * Trang giải mã liên kết rút gọn ẩn thông tin hệ thống và điều hướng tới màn hình duyệt.
 */
export default async function ShortReviewRedirectPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  const cleanCode = (code || "").trim().toLowerCase();
  if (!SHORT_CODE_RE.test(cleanCode)) {
    notFound();
  }
  redirect(`/reviews?ref=${encodeURIComponent(cleanCode)}`);
}
