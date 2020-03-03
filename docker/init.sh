export PATH=/home/janitor/.local/bin:$PATH
export FLASK_APP=janitor.py
while ! flask db migrate && flask db upgrade 2>&1; do
		echo "waiting on db..."
		sleep 5
done

exec ${@}
